import csv
import threading
import hashlib
import hmac
import io
import os
import secrets
import sqlite3
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import jwt
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
STATIC_DIR = BASE_DIR / "static"
DB_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "afiliadopro.db")))
APP_SECRET = os.getenv("APP_SECRET", "dev-only-change-this-secret")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
ADMIN_EMAIL = os.getenv(
    "ADMIN_EMAIL",
    "shoppro.suporte1@gmail.com"
).strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
SHOPEE_APP_ID = os.getenv("SHOPEE_APP_ID", "").strip()
SHOPEE_APP_SECRET = os.getenv("SHOPEE_APP_SECRET", "").strip()
SHOPEE_ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"
JWT_ALGORITHM = "HS256"
TOKEN_DAYS = 7

PLANS = {
    "free": {
        "name": "Free", "price": 0, "commission_max": 20,
        "text_daily": 5, "hashtag_daily": 5, "links_max": 20,
        "favorites_max": 20, "history_days": 7, "radar_limit": None,
    },
    "starter": {
        "name": "Starter", "price": 19.90, "commission_max": 25,
        "text_daily": 30, "hashtag_daily": 30, "links_max": 200,
        "favorites_max": 200, "history_days": 30, "radar_limit": None,
    },
    "pro": {
        "name": "Pro", "price": 39.90, "commission_max": 30,
        "text_daily": 100, "hashtag_daily": 100, "links_max": None,
        "favorites_max": None, "history_days": 90, "radar_limit": None,
    },
    "premium": {
        "name": "Premium", "price": 69.90, "commission_max": None,
        "text_daily": 200, "hashtag_daily": 200, "links_max": None,
        "favorites_max": None, "history_days": 365, "radar_limit": None,
    },
}

app = FastAPI(title="ShopPro API", version="1.0.0")
security = HTTPBearer(auto_error=False)


def utcnow():
    return datetime.now(timezone.utc)


def now_iso():
    return utcnow().isoformat()


def db_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            plan TEXT NOT NULL DEFAULT 'free',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            name TEXT NOT NULL,
            image_url TEXT,
            price REAL,
            category TEXT,
            commission_percent REAL,
            sales_count INTEGER,
            sales_period TEXT,
            trend_percent REAL,
            source_url TEXT,
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_products_owner ON products(owner_id);
        CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            url TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(user_id, product_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS generations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            product_name TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        
        CREATE TABLE IF NOT EXISTS product_sales_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            sales_count INTEGER NOT NULL,
            recorded_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_sales_history_product_date
        ON product_sales_history(product_id, recorded_at);

        """)
init_db()
with db_conn() as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.commit()

def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
    return salt.hex() + "$" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        candidate = hash_password(password, bytes.fromhex(salt_hex)).split("$", 1)[1]
        return hmac.compare_digest(candidate, digest_hex)
    except Exception:
        return False


def issue_token(user):
    payload = {
        "sub": str(user["id"]),
        "exp": utcnow() + timedelta(days=TOKEN_DAYS),
        "iat": utcnow(),
    }
    return jwt.encode(payload, APP_SECRET, algorithm=JWT_ALGORITHM)


def current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(401, "Faça login para continuar.")
    try:
        payload = jwt.decode(credentials.credentials, APP_SECRET, algorithms=[JWT_ALGORITHM])
        uid = int(payload["sub"])
    except Exception:
        raise HTTPException(401, "Sessão inválida ou expirada. Entre novamente.")
    with db_conn() as conn:
        row = conn.execute("SELECT id,name,email,plan,created_at FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        raise HTTPException(401, "Usuário não encontrado.")
    return dict(row)
def require_admin(user=Depends(current_user)):
    if user["email"].strip().lower() != ADMIN_EMAIL:
        raise HTTPException(
            status_code=403,
            detail="Acesso exclusivo ao administrador."
        )
    return user

def plan_for(user):
    return PLANS.get(user["plan"], PLANS["free"])


def enforce_daily_limit(user, kind):
    limits = plan_for(user)
    field = "hashtag_daily" if kind == "hashtags" else "text_daily"
    limit = limits[field]
    since = (utcnow() - timedelta(hours=24)).isoformat()
    with db_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM generations WHERE user_id=? AND kind=? AND created_at>=?",
            (user["id"], kind, since)
        ).fetchone()[0]
    if count >= limit:
        raise HTTPException(429, f"Você atingiu o limite de {limit} gerações de {kind} nas últimas 24 horas.")
    return limit - count


def clean_product(row):
    result = dict(row)
    # Never expose another user's private manual products.
    return result


def valid_http_url(value):
    return value is None or value == "" or value.startswith(("https://", "http://"))


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: str
    password: str
class GoogleLoginIn(BaseModel):
    credential: str = Field(min_length=1)

class ProductIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    image_url: Optional[str] = None
    price: Optional[float] = Field(default=None, ge=0)
    category: Optional[str] = Field(default=None, max_length=100)
    commission_percent: Optional[float] = Field(default=None, ge=0, le=100)
    sales_count: Optional[int] = Field(default=None, ge=0)
    sales_period: Optional[str] = Field(default=None, max_length=80)
    trend_percent: Optional[float] = None
    source_url: Optional[str] = None


class LinkIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=8, max_length=2000)


class GenerateIn(BaseModel):
    kind: str = Field(pattern="^(text|hashtags)$")
    product_name: str = Field(min_length=1, max_length=200)
    features: str = Field(default="", max_length=2000)
    price: str = Field(default="", max_length=100)
    link: str = Field(default="", max_length=2000)
    channel: str = Field(default="Instagram", max_length=50)
    style: str = Field(default="Persuasivo", max_length=50)




class ScriptIn(BaseModel):
    product_name: str = Field(min_length=1, max_length=200)
    features: str = Field(default="", max_length=2000)
    price: str = Field(default="", max_length=100)
    link: str = Field(default="", max_length=2000)
    channel: str = Field(default="TikTok", max_length=50)
    style: str = Field(min_length=1, max_length=80)
    duration: int = Field(ge=10, le=60)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "ShopPro"}


@app.post("/api/auth/register")
def register(body: RegisterIn):
    email = body.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Informe um e-mail válido.")
    with db_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users(name,email,password_hash,plan,created_at) VALUES(?,?,?,?,?)",
                (body.name.strip(), email, hash_password(body.password), "free", now_iso())
            )
            conn.commit()
            uid = cur.lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Este e-mail já está cadastrado.")
        user = conn.execute("SELECT id,name,email,plan,created_at FROM users WHERE id=?", (uid,)).fetchone()
    user = dict(user)
    return {"token": issue_token(user), "user": user}
@app.post("/api/auth/google")
def login_google(body: GoogleLoginIn):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=500,
            detail="O login com Google não está configurado no servidor."
        )

    try:
        info = id_token.verify_oauth2_token(
            body.credential,
            google_requests.Request(),
            GOOGLE_CLIENT_ID
        )
    except ValueError as exc:
        print(f"Erro na validação do Google: {exc}")
        raise HTTPException(
            status_code=401,
            detail="Não foi possível validar sua conta Google. Tente novamente."
        )

    email = str(info.get("email", "")).strip().lower()
    name = str(info.get("name", "")).strip()
    google_sub = info.get("sub")

    if not email or not google_sub or info.get("email_verified") is not True:
        raise HTTPException(
            status_code=401,
            detail="O Google não confirmou seu e-mail."
        )

    if not name:
        name = email.split("@")[0][:80] or "Usuário"

    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, name, email, plan, created_at "
            "FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if row:
            user = dict(row)
        else:
            random_password = secrets.token_urlsafe(48)
            try:
                cur = conn.execute(
                    "INSERT INTO users "
                    "(name, email, password_hash, plan, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        name[:80],
                        email,
                        hash_password(random_password),
                        "free",
                        now_iso()
                    )
                )
                conn.commit()

                row = conn.execute(
                    "SELECT id, name, email, plan, created_at "
                    "FROM users WHERE id = ?",
                    (cur.lastrowid,)
                ).fetchone()
                user = dict(row)

            except sqlite3.IntegrityError:
                raise HTTPException(
                    status_code=409,
                    detail="Não foi possível criar a conta. Tente novamente."
                )

    return {
        "token": issue_token(user),
        "user": user
    }


@app.get("/api/auth/google/config")
def google_login_config():
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=500,
            detail="O login com Google não está configurado."
        )
    return {"client_id": GOOGLE_CLIENT_ID}

@app.post("/api/auth/login")
def login(body: LoginIn):
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=?", (body.email.strip().lower(),)).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "E-mail ou senha incorretos.")
    user = {k: row[k] for k in ("id", "name", "email", "plan", "created_at")}
    return {"token": issue_token(user), "user": user}


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return {"user": user, "plan": plan_for(user)}


@app.get("/api/plans")
def plans():
    return {"plans": PLANS}


@app.get("/api/radar/products")
def radar_products(
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_commission: Optional[float] = None,
    min_sales: Optional[int] = None,
    sort: str = "recent",
    section: str = "today",
    user=Depends(current_user),
):
    maybe_start_auto_shopee_refresh(user)

    plan = plan_for(user)
    ceiling = plan["commission_max"]
    where = ["(owner_id IS NULL OR owner_id=?)"]
    args = [user["id"]]
    if ceiling is not None:
        where.append("(commission_percent IS NULL OR commission_percent<=?)")
        args.append(ceiling)
    if category:
        where.append("LOWER(COALESCE(category,''))=LOWER(?)")
        args.append(category)
    if min_price is not None:
        where.append("price>=?")
        args.append(min_price)
    if max_price is not None:
        where.append("price<=?")
        args.append(max_price)
    if min_commission is not None:
        where.append("commission_percent>=?")
        args.append(min_commission)
    if min_sales is not None:
        where.append("sales_count>=?")
        args.append(min_sales)
    
    if section == "trending":
        where.append("sales_count IS NOT NULL")
    elif section == "top_sales":
        where.append("sales_count IS NOT NULL")
    elif section == "high_commission":
        where.append("commission_percent IS NOT NULL")

    order_by = {
        "recent": "updated_at DESC",
        "popularity": "sales_count DESC",
        "trend": "CASE WHEN trend_percent IS NOT NULL THEN 0 ELSE 1 END ASC, trend_percent DESC, sales_count DESC",
        "commission": "commission_percent DESC",
        "price_asc": "price ASC",
        "price_desc": "price DESC",
    }.get(sort, "updated_at DESC")
    query = f"SELECT * FROM products WHERE {' AND '.join(where)} ORDER BY {order_by}"
    with db_conn() as conn:
        rows = conn.execute(query, args).fetchall()
        favs = {r["product_id"] for r in conn.execute("SELECT product_id FROM favorites WHERE user_id=?", (user["id"],))}
    products = []
    for row in rows:
        item = clean_product(row)
        item["is_favorite"] = item["id"] in favs
        item["commission_value"] = round(item["price"] * item["commission_percent"] / 100, 2) if item["price"] is not None and item["commission_percent"] is not None else None
        products.append(item)
    return {"products": products, "limit": None, "total_returned": len(products),
            "data_notice": None if products else "Ainda não há produtos cadastrados nesta seleção. Cadastre um produto manualmente ou importe um CSV. Não exibimos dados fictícios."}


@app.get("/api/radar/shopee-search")
def shopee_search(keyword: str, page: int = 1, user=Depends(current_user)):
    """Search Shopee Affiliate product offers and cache results in the shared radar."""
    if not SHOPEE_APP_ID or not SHOPEE_APP_SECRET:
        raise HTTPException(503, "Configure SHOPEE_APP_ID e SHOPEE_APP_SECRET no arquivo .env e reinicie o servidor.")
    keyword = keyword.strip()[:100]
    if len(keyword) < 2:
        raise HTTPException(400, "Digite pelo menos 2 caracteres para buscar produtos na Shopee.")
    page = max(1, min(page, 1000))
    gql_keyword = json.dumps(keyword, ensure_ascii=False)
    query = (
        "query { productOfferV2(keyword: " + gql_keyword +
        f", listType: 1, sortType: 5, page: {page}, limit: 30) {{ "
        "nodes { itemId productName productLink offerLink imageUrl priceMin priceMax sales "
        "ratingStar commissionRate sellerCommissionRate shopeeCommissionRate commission shopId shopName } "
        "pageInfo { page limit hasNextPage } } }"
    )
    payload = json.dumps({"query": query}, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time()))
    signature = hashlib.sha256((SHOPEE_APP_ID + timestamp + payload + SHOPEE_APP_SECRET).encode("utf-8")).hexdigest()
    request = urllib.request.Request(
        SHOPEE_ENDPOINT,
        data=payload.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"SHA256 Credential={SHOPEE_APP_ID}, Timestamp={timestamp}, Signature={signature}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise HTTPException(502, f"A Shopee retornou HTTP {exc.code}. Confira as credenciais e permissões. {detail}")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(502, "Não foi possível conectar à API da Shopee. Tente novamente em instantes.") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(502, "A API da Shopee retornou uma resposta inválida.") from exc

    if result.get("errors"):
        errors = result["errors"]
        message = "; ".join(str(e.get("message", "Erro GraphQL")) for e in errors[:2])
        code = errors[0].get("extensions", {}).get("code") if errors else None
        if str(code) == "10020":
            message = "Credenciais/assinatura inválidas (erro 10020). Confira App ID, Secret e horário do servidor."
        elif str(code) == "10030":
            message = "Limite de chamadas da Shopee atingido. Aguarde antes de tentar novamente."
        elif str(code) == "10035":
            message = "A aplicação não tem permissão para este recurso da Open API (erro 10035)."
        raise HTTPException(502, f"Erro na API Shopee: {message}")

    data = (result.get("data") or {}).get("productOfferV2") or {}
    nodes = data.get("nodes") or []
    now = now_iso()
    inserted = 0
    with db_conn() as conn:
        for node in nodes:
            name = str(node.get("productName") or "Produto Shopee").strip()[:200]
            raw_commission = node.get("commissionRate")
            try:
                commission = float(raw_commission) * 100 if raw_commission is not None else None
            except (TypeError, ValueError):
                commission = None
            if commission is not None and commission > 100:
                commission = None
            try:
                price = float(node.get("priceMin")) if node.get("priceMin") is not None else None
            except (TypeError, ValueError):
                price = None
            try:
                sales = int(float(node.get("sales"))) if node.get("sales") is not None else None
            except (TypeError, ValueError):
                sales = None
            url = node.get("offerLink") or node.get("productLink")
            image_url = node.get("imageUrl")
            shop_name = str(node.get("shopName") or "Shopee")[:100]
            if not name or not valid_http_url(url) or not valid_http_url(image_url):
                continue
            
            existing = conn.execute(
                "SELECT id FROM products WHERE source='shopee' AND source_url=? LIMIT 1",
                (url,)
            ).fetchone()

            values = (
                name, image_url, price, shop_name,
                commission, sales, url, now
            )

            if existing:
                product_id = existing["id"]
                conn.execute("""
                    UPDATE products
                    SET name=?, image_url=?, price=?, category=?,
                        commission_percent=?, sales_count=?,
                        source_url=?, updated_at=?
                    WHERE id=?
                """, values + (product_id,))
            else:
                cursor = conn.execute("""
                    INSERT INTO products(
                        owner_id, name, image_url, price, category,
                        commission_percent, sales_count, sales_period,
                        trend_percent, source_url, source, created_at, updated_at
                    )
                    VALUES(NULL, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, 'shopee', ?, ?)
                """, (
                    name, image_url, price, shop_name,
                    commission, sales, url, now, now
                ))
                product_id = cursor.lastrowid
                inserted += 1

            
            # Registra uma leitura diária e calcula a variação real.
            if sales is not None:
                ja_registrado_hoje = conn.execute("""
                    SELECT 1
                    FROM product_sales_history
                    WHERE product_id = ?
                      AND date(recorded_at) = date(?)
                    LIMIT 1
                """, (product_id, now)).fetchone()

                if not ja_registrado_hoje:
                    anterior = conn.execute("""
                        SELECT sales_count
                        FROM product_sales_history
                        WHERE product_id = ?
                        ORDER BY recorded_at DESC
                        LIMIT 1
                    """, (product_id,)).fetchone()

                    if anterior and anterior["sales_count"] > 0:
                        variacao = round(
                            (sales - anterior["sales_count"])
                            / anterior["sales_count"] * 100,
                            2
                        )
                        conn.execute(
                            "UPDATE products SET trend_percent = ? WHERE id = ?",
                            (variacao, product_id)
                        )

                    conn.execute("""
                        INSERT INTO product_sales_history(
                            product_id, sales_count, recorded_at
                        )
                        VALUES (?, ?, ?)
                    """, (product_id, sales, now))

        conn.commit()
        ceiling = plan_for(user)["commission_max"]
        where = ["source='shopee'", "LOWER(name) LIKE LOWER(?)"]
        args = [f"%{keyword}%"]
        if ceiling is not None:
            where.append("(commission_percent IS NULL OR commission_percent<=?)")
            args.append(ceiling)
        rows = conn.execute(f"SELECT * FROM products WHERE {' AND '.join(where)} ORDER BY commission_percent DESC", args).fetchall()
        favs = {r["product_id"] for r in conn.execute("SELECT product_id FROM favorites WHERE user_id=?", (user["id"],))}
    products = []
    for row in rows:
        item = clean_product(row)
        item["is_favorite"] = item["id"] in favs
        item["commission_value"] = round(item["price"] * item["commission_percent"] / 100, 2) if item["price"] is not None and item["commission_percent"] is not None else None
        products.append(item)
    page_info = data.get("pageInfo") or {}
    return {"products": products, "received": len(nodes), "new_products": inserted,
            "page": page_info.get("page", page), "has_next_page": page_info.get("hasNextPage", False),
            "message": f"Busca Shopee concluída: {len(products)} produto(s) disponíveis para o seu plano."}
SHOPEE_AUTO_KEYWORDS = [
    "casa",
    "beleza",
    "moda",
    "eletrônicos",
    "acessórios",
]

SHOPEE_AUTO_INTERVAL_SECONDS = 15 * 60
_shopee_auto_lock = threading.Lock()




def _run_auto_shopee_refresh(user):
    try:
        print("[Radar Shopee automático] Iniciando atualização.")

        for keyword in SHOPEE_AUTO_KEYWORDS:
            for page in range(1, 4):
                try:
                    resultado = shopee_search(
                        keyword=keyword,
                        page=page,
                        user=user,
                    )

                    recebidos = resultado.get("received", 0)
                    novos = resultado.get("new_products", 0)
                    tem_proxima = resultado.get("has_next_page", False)

                    print(
                        f"[Radar Shopee automático] "
                        f"Busca: {keyword} | "
                        f"Página: {page} | "
                        f"Recebidos: {recebidos} | "
                        f"Produtos novos: {novos} | "
                        f"Próxima página: {tem_proxima}"
                    )

                    if not tem_proxima:
                        break

                except Exception as exc:
                    print(
                        f"[Radar Shopee automático] "
                        f"Erro na busca '{keyword}', "
                        f"página {page}: {exc}"
                    )
                    break

                time.sleep(2)

        print("[Radar Shopee automático] Atualização finalizada.")

    finally:
        _shopee_auto_lock.release()


def maybe_start_auto_shopee_refresh(user):
    if not SHOPEE_APP_ID or not SHOPEE_APP_SECRET:
        return

    if not _shopee_auto_lock.acquire(blocking=False):
        return

    try:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?",
                ("shopee_auto_last_attempt",),
            ).fetchone()

            last_attempt = float(row["value"]) if row else 0
            now = time.time()

            if now - last_attempt < SHOPEE_AUTO_INTERVAL_SECONDS:
                _shopee_auto_lock.release()
                return

            conn.execute(
                """
                INSERT INTO app_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key)
                DO UPDATE SET value = excluded.value
                """,
                ("shopee_auto_last_attempt", str(now)),
            )
            conn.commit()

        threading.Thread(
            target=_run_auto_shopee_refresh,
            args=(dict(user),),
            daemon=True,
        ).start()

    except Exception as exc:
        if _shopee_auto_lock.locked():
            _shopee_auto_lock.release()
        print(f"[Radar Shopee automático] Falha ao iniciar: {exc}")

@app.post("/api/products")
def create_product(body: ProductIn, user=Depends(current_user)):
    if not valid_http_url(body.image_url) or not valid_http_url(body.source_url):
        raise HTTPException(400, "URLs de imagem e produto devem começar com http:// ou https://.")
    now = now_iso()
    with db_conn() as conn:
        cur = conn.execute("""
            INSERT INTO products(owner_id,name,image_url,price,category,commission_percent,sales_count,sales_period,trend_percent,source_url,source,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (user["id"], body.name.strip(), body.image_url, body.price, body.category,
              body.commission_percent, body.sales_count, None, body.trend_percent,
              body.source_url, "manual", now, now))
        conn.commit()
        row = conn.execute("SELECT * FROM products WHERE id=?", (cur.lastrowid,)).fetchone()
    return {"product": clean_product(row)}


@app.post("/api/products/import-csv")
async def import_csv(file: UploadFile = File(...), user=Depends(current_user)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Envie um arquivo .csv.")
    raw = await file.read()
    if len(raw) > 2_000_000:
        raise HTTPException(413, "O CSV deve ter no máximo 2 MB.")
    try:
        content = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))
        required = {"name"}
        if not reader.fieldnames or not required.issubset({h.strip().lower() for h in reader.fieldnames}):
            raise HTTPException(400, "O CSV precisa ter pelo menos a coluna name.")
        headers = {h.strip().lower(): h for h in reader.fieldnames}
        added = 0
        now = now_iso()
        with db_conn() as conn:
            for row in reader:
                def val(key):
                    original = headers.get(key)
                    return (row.get(original) or "").strip() if original else ""
                name = val("name")
                if not name:
                    continue
                def number(key):
                    value = val(key).replace("%", "").replace(",", ".")
                    try:
                        return float(value) if value else None
                    except ValueError:
                        return None
                price = number("price")
                commission = number("commission_percent")
                sales = number("sales_count")
                trend = number("trend_percent")
                image_url = val("image_url") or None
                source_url = val("source_url") or None
                if not valid_http_url(image_url):
                    image_url = None
                if not valid_http_url(source_url):
                    source_url = None
                conn.execute("""
                    INSERT INTO products(owner_id,name,image_url,price,category,commission_percent,sales_count,sales_period,trend_percent,source_url,source,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (user["id"], name[:200], image_url, price, val("category") or None,
                      commission if commission is not None and 0 <= commission <= 100 else None,
                      int(sales) if sales is not None and sales >= 0 else None,
                      val("sales_period") or None, trend, source_url, "csv", now, now))
                added += 1
            conn.commit()
        return {"imported": added, "message": f"{added} produto(s) importado(s)."}
    except UnicodeDecodeError:
        raise HTTPException(400, "Não foi possível ler o CSV. Salve o arquivo em UTF-8.")


@app.post("/api/products/{product_id}/favorite")
def toggle_favorite(product_id: int, user=Depends(current_user)):
    with db_conn() as conn:
        product = conn.execute("SELECT id,owner_id,commission_percent FROM products WHERE id=? AND (owner_id IS NULL OR owner_id=?)", (product_id, user["id"])).fetchone()
        if not product:
            raise HTTPException(404, "Produto não encontrado.")
        ceiling = plan_for(user)["commission_max"]
        if ceiling is not None and product["commission_percent"] is not None and product["commission_percent"] > ceiling:
            raise HTTPException(403, "Este produto ultrapassa o limite de comissão do seu plano.")
        existing = conn.execute("SELECT 1 FROM favorites WHERE user_id=? AND product_id=?", (user["id"], product_id)).fetchone()
        if existing:
            conn.execute("DELETE FROM favorites WHERE user_id=? AND product_id=?", (user["id"], product_id))
            conn.commit()
            return {"favorite": False}
        maximum = plan_for(user)["favorites_max"]
        count = conn.execute("SELECT COUNT(*) FROM favorites WHERE user_id=?", (user["id"],)).fetchone()[0]
        if maximum is not None and count >= maximum:
            raise HTTPException(429, f"Seu plano permite até {maximum} favoritos.")
        conn.execute("INSERT INTO favorites(user_id,product_id,created_at) VALUES(?,?,?)", (user["id"], product_id, now_iso()))
        conn.commit()
        return {"favorite": True}


@app.get("/api/favorites")
def favorites(user=Depends(current_user)):
    ceiling = plan_for(user)["commission_max"]
    query = """
        SELECT p.*, f.created_at AS favorited_at FROM favorites f
        JOIN products p ON p.id=f.product_id
        WHERE f.user_id=? AND (p.owner_id IS NULL OR p.owner_id=?)
    """
    args = [user["id"], user["id"]]
    if ceiling is not None:
        query += " AND (p.commission_percent IS NULL OR p.commission_percent<=?)"
        args.append(ceiling)
    query += " ORDER BY f.created_at DESC"
    with db_conn() as conn:
        rows = conn.execute(query, args).fetchall()
    result = [clean_product(r) for r in rows]
    for p in result:
        p["is_favorite"] = True
        p["commission_value"] = round(p["price"] * p["commission_percent"] / 100, 2) if p["price"] is not None and p["commission_percent"] is not None else None
    return {"products": result}


@app.get("/api/links")
def list_links(user=Depends(current_user)):
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM links WHERE user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()
    return {"links": [dict(r) for r in rows], "limit": plan_for(user)["links_max"]}


@app.post("/api/links")
def create_link(body: LinkIn, user=Depends(current_user)):
    if not body.url.startswith(("https://", "http://")):
        raise HTTPException(400, "O link precisa começar com http:// ou https://.")
    maximum = plan_for(user)["links_max"]
    with db_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM links WHERE user_id=?", (user["id"],)).fetchone()[0]
        if maximum is not None and count >= maximum:
            raise HTTPException(429, f"Seu plano permite até {maximum} links salvos.")
        cur = conn.execute("INSERT INTO links(user_id,label,url,created_at) VALUES(?,?,?,?)",
                           (user["id"], body.label.strip(), body.url.strip(), now_iso()))
        conn.commit()
        row = conn.execute("SELECT * FROM links WHERE id=?", (cur.lastrowid,)).fetchone()
    return {"link": dict(row)}


@app.delete("/api/links/{link_id}")
def delete_link(link_id: int, user=Depends(current_user)):
    with db_conn() as conn:
        cur = conn.execute("DELETE FROM links WHERE id=? AND user_id=?", (link_id, user["id"]))
        conn.commit()
    if not cur.rowcount:
        raise HTTPException(404, "Link não encontrado.")
    return {"deleted": True}


@app.get("/api/history")
def history(user=Depends(current_user)):
    cutoff = (utcnow() - timedelta(days=plan_for(user)["history_days"])).isoformat()
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM generations WHERE user_id=? AND created_at>=? ORDER BY created_at DESC LIMIT 300",
            (user["id"], cutoff)
        ).fetchall()
    return {"history": [dict(r) for r in rows], "days": plan_for(user)["history_days"]}


@app.post("/api/ai/generate")
async def generate(body: GenerateIn, user=Depends(current_user)):
    remaining = enforce_daily_limit(user, body.kind)
    if not GEMINI_API_KEY:
        raise HTTPException(503, "A geração por IA ainda não está configurada. Adicione GEMINI_API_KEY ao arquivo .env. Você pode continuar usando o Radar, produtos, favoritos, links e calculadora.")
    prompt_kind = "Crie 3 opções de texto promocional" if body.kind == "text" else "Crie 3 conjuntos de hashtags relevantes"
    prompt = f"""Você é um assistente de marketing de afiliados no Brasil. Escreva em português brasileiro.
Não invente descontos, escassez, avaliações, estoque ou características. Use apenas os dados informados.
Tarefa: {prompt_kind}.
Produto: {body.product_name}
Características: {body.features or 'não informado'}
Preço: {body.price or 'não informado'}
Link: {body.link or 'não informado'}
Canal: {body.channel}
Estilo: {body.style}
Seja claro, útil e honesto."""
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = await client.aio.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        content = (response.text or "").strip()
        if not content:
            raise RuntimeError("A IA não retornou texto.")
    except Exception as exc:
        detalhe = str(exc).replace(GEMINI_API_KEY, "[CHAVE_OCULTA]")
        print(f"Erro na geração Gemini ({type(exc).__name__}): {detalhe}")
        raise HTTPException(502, "Não foi possível gerar o conteúdo. Consulte o terminal do servidor.")
    with db_conn() as conn:
        conn.execute("INSERT INTO generations(user_id,kind,product_name,content,created_at) VALUES(?,?,?,?,?)",
                     (user["id"], body.kind, body.product_name, content, now_iso()))
        conn.commit()
    return {"content": content, "kind": body.kind, "remaining_after": remaining - 1}


@app.get("/api/admin/users")
def admin_list_users(admin=Depends(require_admin)):
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, name, email, plan, created_at
            FROM users
            ORDER BY created_at DESC
            """
        ).fetchall()

    return {"users": [dict(row) for row in rows]}

@app.post("/api/admin/users/{user_id}/plan")
def admin_set_plan(
    user_id: int,
    plan: str,
    admin=Depends(require_admin)
):
    if plan not in PLANS:
        raise HTTPException(400, "Plano inválido.")
    with db_conn() as conn:
        cur = conn.execute("UPDATE users SET plan=? WHERE id=?", (plan, user_id))
        conn.commit()
    if not cur.rowcount:
        raise HTTPException(404, "Usuário não encontrado.")
    return {"updated": True, "user_id": user_id, "plan": plan}


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.post("/api/ai/scripts")
async def generate_script(body: ScriptIn, user=Depends(current_user)):
    if user.get("plan") != "premium":
        raise HTTPException(403, "A geração de roteiros é exclusiva do plano Premium.")
    if not GEMINI_API_KEY:
        raise HTTPException(503, "A IA não está configurada. Configure GEMINI_API_KEY no arquivo .env.")
    allowed_styles = {
        "A.I.D.A.", "D.U.R.O.", "P.A.S.", "A.I.C.A.", "A.B.C.", "U.G.C.",
        "Problema → Solução", "Antes → Depois", "Quebra de Objeção",
        "Comparação → Alternativa", "Curiosidade → Revelação",
        "Descoberta → Demonstração → Benefício",
        "Desejo → Transformação → Ação", "Curiosidade e Descoberta",
        "Comparação e Contraste", "Identificação com o Público",
        "Quebra de Padrão", "Surpresa", "VTSD"
    }
    if body.style not in allowed_styles:
        raise HTTPException(400, "Estilo de roteiro inválido.")
    prompt = f"""Você é roteirista de vídeos curtos para afiliados brasileiros.
Escreva em português brasileiro um roteiro falado para vídeo de aproximadamente
{body.duration} segundos, no canal {body.channel}.
Estilo/metodologia selecionada: {body.style}.
Respeite o estilo escolhido sem inventar etapas específicas de metodologias que
não foram definidas no pedido.
Produto: {body.product_name}
Características verdadeiras informadas: {body.features or 'não informado'}
Preço informado: {body.price or 'não informado'}
Link: {body.link or 'não informado'}
Crie: 1) gancho inicial, 2) fala completa, 3) sugestão de cenas/textos na tela,
4) chamada para ação. Ajuste o tamanho da fala à duração escolhida.
Não invente descontos, avaliações, escassez, estoque, resultados ou características.
Não diga que o vídeo foi criado; entregue somente o roteiro."""
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL, contents=prompt
        )
        content = (response.text or "").strip()
        if not content:
            raise RuntimeError("A IA não retornou texto.")
    except Exception:
        raise HTTPException(502, "Não foi possível gerar o roteiro. Verifique a configuração e os limites da IA.")
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO generations(user_id,kind,product_name,content,created_at) VALUES(?,?,?,?,?)",
            (user["id"], "script", body.product_name, content, now_iso())
        )
        conn.commit()
    return {"content": content, "kind": "script"}
