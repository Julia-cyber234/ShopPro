const $ = (id) => document.getElementById(id);
const state = { token: localStorage.getItem("afp_token"), user: null, plan: null, section: "today", products: [], authMode: "login", currentView: "radar", pendingProduct: null };
const titles = {radar:"Radar de produtos",favorites:"Favoritos",links:"Meus links",ai:"Gerador de conteúdo",calculator:"Calculadora de comissões",history:"Histórico",scripts:"Roteiros",videos:"Criar vídeos",support:"Suporte",plans:"Planos e limites",admin:"Administração"};
function esc(s=""){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function money(n){return n==null?"—":Number(n).toLocaleString("pt-BR",{style:"currency",currency:"BRL"});}
function toast(msg,error=false){const el=$("toast");el.textContent=msg;el.classList.toggle("error",error);el.classList.remove("hidden");clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>el.classList.add("hidden"),4200);}
async function api(path,opts={}){const headers={...(opts.headers||{})};if(state.token)headers.Authorization=`Bearer ${state.token}`;if(opts.body && !(opts.body instanceof FormData))headers["Content-Type"]="application/json";const res=await fetch(path,{...opts,headers});let data={};try{data=await res.json()}catch{}if(!res.ok){if(res.status===401 && state.token){logout(false);showAuth()}throw new Error(data.detail||"Não foi possível concluir a operação.")}return data;}

async function handleGoogleCredential(response) {
  const message = $("auth-message");
  message.textContent = "Validando sua conta Google...";

  try {
    const res = await fetch("/api/auth/google", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ credential: response.credential })
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.detail || "Não foi possível entrar com Google.");
    }

    state.token = data.token;
    localStorage.setItem("afp_token", data.token);
    state.user = data.user;

    const me = await api("/api/auth/me");
    state.plan = me.plan;

    showApp();
    await renderView("radar");
  } catch (err) {
    message.textContent = err.message || "Erro ao entrar com Google.";
  }
}

async function initializeGoogleLogin() {
  const container = $("google-button");
  if (!container) return;

  try {
    const configResponse = await fetch("/api/auth/google/config");
    const config = await configResponse.json();

    if (!configResponse.ok || !config.client_id) {
      throw new Error(config.detail || "Client ID do Google não configurado.");
    }

    const waitForGoogle = () => {
      if (!window.google?.accounts?.id) {
        setTimeout(waitForGoogle, 300);
        return;
      }

      window.google.accounts.id.initialize({
        client_id: config.client_id,
        callback: handleGoogleCredential
      });

      window.google.accounts.id.renderButton(container, {
        theme: "outline",
        size: "large",
        shape: "rectangular",
        text: "signin_with",
        width: 280,
        locale: "pt-BR"
      });
    };

    waitForGoogle();
  } catch (err) {
    $("auth-message").textContent = err.message;
  }
}
function showAuth(){ $("auth-screen").classList.remove("hidden");$("view").classList.add("hidden");document.querySelector(".topbar").classList.add("hidden");}
function showApp(){ const adminNav = $("admin-nav"); if (adminNav) adminNav.style.display = state.user?.email?.trim().toLowerCase() === "shoppro.suporte1@gmail.com" ? "" : "none"; $("auth-screen").classList.add("hidden");$("view").classList.remove("hidden");document.querySelector(".topbar").classList.remove("hidden");$("user-name").textContent=state.user.name;$("user-plan").textContent=`Plano ${state.plan.name}`;$("side-plan").textContent=state.plan.name;$("avatar").textContent=(state.user.name||"A").slice(0,1).toUpperCase();}
function logout(show=true){state.token=null;state.user=null;state.plan=null;localStorage.removeItem("afp_token");if(show)showAuth();}
function setAuthMode(mode){state.authMode=mode;$("tab-login").classList.toggle("selected",mode==="login");$("tab-register").classList.toggle("selected",mode==="register");$("name-wrap").classList.toggle("hidden",mode!=="register");$("auth-name").required=mode==="register";$("auth-submit").textContent=mode==="login"?"Entrar":"Criar conta";$("auth-password").autocomplete=mode==="login"?"current-password":"new-password";$("auth-message").textContent="";}
async function loadSession(){if(!state.token){showAuth();return;}try{const d=await api("/api/auth/me");state.user=d.user;state.plan=d.plan;showApp();await renderView("radar");}catch(e){showAuth();}}
function activateNav(view){state.currentView=view;document.querySelectorAll(".nav[data-view]").forEach(b=>b.classList.toggle("active",b.dataset.view===view));$("page-title").textContent=titles[view]||"ShopPro";}

async function renderView(view){
  activateNav(view);
  if (view === "admin") return renderAdmin();
  if(view==="radar"){
    $("view").innerHTML=radarTemplate();
    bindRadar();
    await loadRadar();

    setTimeout(()=>{if($("product-grid"))loadRadar();},15000);
    setTimeout(()=>{if($("product-grid"))loadRadar();},35000);
    setTimeout(()=>{if($("product-grid"))loadRadar();},60000);

    return;
  }

  if(view==="favorites"){await renderFavorites();return;}
  if(view==="links"){await renderLinks();return;}
  if(view==="ai"){renderAI();return;}
  if(view==="calculator"){renderCalculator();return;}
  if(view==="history"){await renderHistory();return;}
  if(view==="scripts"){renderScripts();return;}
  if(view==="videos"){renderVideos();return;}
  if(view==="support"){renderSupport();return;}
  if(view==="plans"){renderPlans();return;}
}

function radarTemplate(){return `<div class="welcome-row"><div><h2>Radar de hoje <span class="live-pill"><i></i> Dados cadastrados</span></h2><p class="muted">Busque ofertas reais da Shopee e acompanhe as oportunidades no seu radar.</p></div><button class="secondary" id="refresh">↻ Atualizar</button></div><div class="stats-grid"><div class="stat-card"><span class="stat-icon purple">⌁</span><span class="stat-label">Produtos visíveis</span><strong id="stat-products">0</strong><small>Radar ilimitado em todos os planos</small></div><div class="stat-card"><span class="stat-icon green">↗</span><span class="stat-label">Novos no radar</span><strong id="stat-new">—</strong><small>Atualizados nas últimas 24h</small></div><div class="stat-card"><span class="stat-icon amber">％</span><span class="stat-label">Maior comissão</span><strong id="stat-commission">—</strong><small>Entre os produtos exibidos</small></div><div class="stat-card"><span class="stat-icon blue">♡</span><span class="stat-label">Favoritos</span><strong id="stat-favorites">0</strong><small>Salvos por você</small></div></div><div class="section-tabs" id="radar-tabs"><button class="selected" data-section="today">Radar de hoje</button><button data-section="trending">Em alta</button><button data-section="high_commission">Maior comissão</button><button data-section="top_sales">Mais vendidos</button></div><div class="filter-panel"><div class="filter-search"><label>Buscar produto<input id="search" placeholder="Nome do produto..."></label></div><div><label>Categoria<input id="category" placeholder="Ex.: Casa"></label></div><div><label>Preço mínimo<input id="min-price" type="number" min="0" placeholder="R$ 0"></label></div><div><label>Preço máximo<input id="max-price" type="number" min="0" placeholder="Sem limite"></label></div><div><label>Ordenar por<select id="sort"><option value="recent">Mais recentes</option><option value="popularity">Popularidade</option><option value="trend">Tendência</option><option value="commission">Comissão</option><option value="price_asc">Menor preço</option><option value="price_desc">Maior preço</option></select></label></div><button class="primary" id="apply-filters">Filtrar</button><button class="primary" id="shopee-search">Buscar na Shopee ↗</button></div><div class="toolbar"><span id="results-label">Produtos</span><div><button class="secondary" id="add-product-btn">＋ Cadastrar produto</button><button class="secondary" id="csv-btn">Importar CSV</button><input type="file" id="csv-file" accept=".csv" class="hidden"></div></div><div id="product-grid" class="product-grid"></div><div id="empty-state" class="empty-state hidden"><div class="empty-icon">⌁</div><h3>Seu radar está pronto para receber produtos</h3><p>Não há produtos nesta seleção. Digite um termo e clique em “Buscar na Shopee”, ou cadastre um produto/import CSV.</p><button class="primary" id="empty-add">＋ Cadastrar primeiro produto</button></div><p class="data-footnote">Comissões, vendas e tendências aparecem apenas quando informadas. O ShopPro não garante vendas ou ganhos.</p>`;}
function bindRadar(){ $("refresh").onclick=loadRadar;$("apply-filters").onclick=loadRadar;$("shopee-search").onclick=async()=>{const keyword=$("search").value.trim();if(keyword.length<2){toast("Digite o nome de um produto para buscar na Shopee.",true);return;}const btn=$("shopee-search");btn.disabled=true;btn.textContent="Buscando...";try{const d=await api(`/api/radar/shopee-search?keyword=${encodeURIComponent(keyword)}`);toast(d.message);await loadRadar()}catch(e){toast(e.message,true)}finally{btn.disabled=false;btn.textContent="Buscar na Shopee ↗"}};$("search").addEventListener("keydown",e=>{if(e.key==="Enter")loadRadar()});$("add-product-btn").onclick=()=>$("product-dialog").showModal();$("empty-add").onclick=()=>$("product-dialog").showModal();$("csv-btn").onclick=()=>$("csv-file").click();$("csv-file").onchange=importCSV;document.querySelectorAll("#radar-tabs button").forEach(b=>b.onclick=()=>{state.section=b.dataset.section;document.querySelectorAll("#radar-tabs button").forEach(x=>x.classList.toggle("selected",x===b));loadRadar()});}
async function loadRadar(){
  try {
    const params=new URLSearchParams({
      section:state.section,
      sort:$("sort")?.value||"recent"
    });
    const cat=$("category")?.value.trim();
    const min=$("min-price")?.value;
    const max=$("max-price")?.value;
    if(cat)params.set("category",cat);
    if(min)params.set("min_price",min);
    if(max)params.set("max_price",max);

    const d=await api(`/api/radar/products?${params}`);
    state.products=d.products;
    const q=($("search")?.value||"").toLowerCase();
    const products=d.products.filter(p=>(p.name||"").toLowerCase().includes(q));

    state.radarFilteredProducts=products;
    state.radarPage=1;

    $("stat-products").textContent=products.length;
    $("stat-new").textContent=products.filter(
      p=>Date.now()-new Date(p.updated_at).getTime()<86400000
    ).length;

    $("stat-commission").textContent=products.some(
      p=>p.commission_percent!=null
    )?Math.max(
      ...products.filter(p=>p.commission_percent!=null).map(p=>p.commission_percent)
    ).toLocaleString("pt-BR")+"%":"—";

    const fav=await api("/api/favorites");
    $("stat-favorites").textContent=fav.products.length;
    renderRadarPage();
  } catch(e) {
    toast(e.message,true);
  }
}

function renderRadarPage(){
  const products=state.radarFilteredProducts||[];
  const size=12;
  const pages=Math.max(1,Math.ceil(products.length/size));
  state.radarPage=Math.max(1,Math.min(state.radarPage||1,pages));

  const first=(state.radarPage-1)*size;
  const visible=products.slice(first,first+size);

  $("results-label").textContent=products.length
    ? `Mostrando ${first+1}–${Math.min(first+size,products.length)} de ${products.length} produtos`
    : "0 produtos";

  $("product-grid").innerHTML=visible.map(productCard).join("");
  $("empty-state").classList.toggle("hidden",products.length>0);

  let nav=$("radar-pagination");
  if(!nav){
    nav=document.createElement("div");
    nav.id="radar-pagination";
    nav.className="radar-pagination";
    $("product-grid").insertAdjacentElement("afterend",nav);
  }

  nav.innerHTML=products.length>size?`
    <button class="secondary" id="radar-prev" ${state.radarPage===1?"disabled":""}>← Anterior</button>
    <span>Página ${state.radarPage} de ${pages}</span>
    <button class="secondary" id="radar-next" ${state.radarPage===pages?"disabled":""}>Próxima →</button>
  `:"";

  $("radar-prev")?.addEventListener("click",()=>{
    state.radarPage--;
    renderRadarPage();
  });

  $("radar-next")?.addEventListener("click",()=>{
    state.radarPage++;
    renderRadarPage();
  });

  visible.forEach(p=>{
    const fav=document.querySelector(`[data-fav="${p.id}"]`);
    if(fav)fav.onclick=()=>toggleFavorite(p.id);

    const save=document.querySelector(`[data-save="${p.id}"]`);
    if(save)save.onclick=()=>openLinkDialog(p);

    const calc=document.querySelector(`[data-calc="${p.id}"]`);
    if(calc)calc.onclick=()=>{state.pendingProduct=p;renderCalculator(p);};

    const gen=document.querySelector(`[data-gen="${p.id}"]`);
    if(gen)gen.onclick=()=>renderAI(p);
  });
}function productCard(p){const image=p.image_url?`<img src="${esc(p.image_url)}" alt="${esc(p.name)}" loading="lazy" onerror="this.remove()">`:`<div class="product-placeholder">◇</div>`;const trend=p.trend_percent==null?"Não informado":`${p.trend_percent>0?"+":""}${p.trend_percent}%`;return `<article class="product-card"><div class="product-image">${image}<span class="product-tag">${esc(p.category||"Sem categoria")}</span><button class="favorite-btn ${p.is_favorite?"on":""}" data-fav="${p.id}" title="Favoritar">${p.is_favorite?"♥":"♡"}</button></div><div class="product-body"><div class="product-category">${esc(p.source||"manual")} · ${p.updated_at?new Date(p.updated_at).toLocaleDateString("pt-BR"):"data não informada"}</div><h3 class="product-title">${esc(p.name)}</h3><div class="product-price">${money(p.price)}</div><div class="product-meta"><div><div class="meta-label">Comissão</div><div class="meta-value good">${p.commission_percent==null?"Não informada":p.commission_percent+"%"}</div></div><div><div class="meta-label">Comissão estimada/venda</div><div class="meta-value">${money(p.commission_value)}</div></div><div><div class="meta-label">Vendas observadas</div><div class="meta-value">${p.sales_count==null?"Não informado":p.sales_count.toLocaleString("pt-BR")}</div></div><div><div class="meta-label">Tendência</div><div class="meta-value">${trend}</div></div></div><div class="product-actions">${p.source_url?`<a href="${esc(p.source_url)}" target="_blank" rel="noopener noreferrer">Abrir produto ↗</a>`:""}<button data-save="${p.id}">Salvar link</button><button data-calc="${p.id}">Calcular</button><button data-gen="${p.id}">Criar texto ✦</button></div></div></article>`;}
async function toggleFavorite(id){try{const d=await api(`/api/products/${id}/favorite`,{method:"POST"});toast(d.favorite?"Produto adicionado aos favoritos.":"Produto removido dos favoritos.");await loadRadar()}catch(e){toast(e.message,true)}}
async function importCSV(e){const file=e.target.files[0];if(!file)return;const fd=new FormData();fd.append("file",file);try{const d=await api("/api/products/import-csv",{method:"POST",body:fd});toast(d.message);await loadRadar()}catch(err){toast(err.message,true)}e.target.value="";}
function openLinkDialog(p){state.pendingProduct=p;$("link-label").value=p.name;$("link-url").value=p.source_url||"";$("link-dialog").showModal();}
async function renderFavorites(){activateNav("favorites");$("view").innerHTML=`<div class="view-card"><h2>Seus favoritos</h2><p class="muted">Acompanhe produtos salvos. A evolução depende de novas atualizações de dados.</p><div id="fav-grid" class="product-grid"></div><div id="fav-empty" class="empty-state hidden"><h3>Nenhum favorito ainda</h3><p>Favorite produtos no Radar para encontrá-los aqui.</p><button class="primary" id="go-radar">Ir para o Radar</button></div></div>`;const d=await api("/api/favorites");$("fav-grid").innerHTML=d.products.map(productCard).join("");$("fav-empty").classList.toggle("hidden",d.products.length>0);$("go-radar").onclick=()=>renderView("radar");d.products.forEach(p=>{const b=document.querySelector(`[data-fav="${p.id}"]`);if(b)b.onclick=()=>toggleFavorite(p.id);const s=document.querySelector(`[data-save="${p.id}"]`);if(s)s.onclick=()=>openLinkDialog(p);const c=document.querySelector(`[data-calc="${p.id}"]`);if(c)c.onclick=()=>renderCalculator(p);const g=document.querySelector(`[data-gen="${p.id}"]`);if(g)g.onclick=()=>renderAI(p)});}
async function renderLinks(){activateNav("links");const d=await api("/api/links");$("view").innerHTML=`<div class="view-card"><div class="welcome-row"><div><h2>Meus links</h2><p class="muted">${d.links.length} salvo(s) · limite ${d.limit==null?"sem limite comercial":d.limit}</p></div><button class="primary" id="new-link">＋ Novo link</button></div><div class="simple-list" id="links-list"></div></div><div class="notice">Salve links de afiliado manualmente. A criação automática de links exige uma integração oficial configurada.</div>`;$("links-list").innerHTML=d.links.map(l=>`<div class="list-row"><div><strong>${esc(l.label)}</strong><small>${esc(l.url)}</small></div><div><button class="secondary" data-copy="${l.id}">Copiar</button> <button class="secondary" data-delete="${l.id}">Excluir</button></div></div>`).join("")||"<p class='muted'>Você ainda não salvou links.</p>";$("new-link").onclick=()=>{state.pendingProduct=null;$("link-label").value="";$("link-url").value="";$("link-dialog").showModal()};d.links.forEach(l=>{document.querySelector(`[data-copy="${l.id}"]`).onclick=async()=>{await navigator.clipboard.writeText(l.url);toast("Link copiado.")};document.querySelector(`[data-delete="${l.id}"]`).onclick=async()=>{try{await api(`/api/links/${l.id}`,{method:"DELETE"});renderLinks();toast("Link excluído.")}catch(e){toast(e.message,true)}}});}
function renderAI(product=null){activateNav("ai");$("view").innerHTML=`<div class="view-card"><h2>Gerador de conteúdo</h2><p class="muted">Crie textos promocionais e hashtags com base nas informações fornecidas.</p><div class="notice">A geração usa a API de IA quando configurada no backend. Os limites do plano são aplicados por tipo de geração.</div><form id="ai-form"><label>Tipo de geração<select id="ai-kind"><option value="text">Texto promocional</option><option value="hashtags">Hashtags</option></select></label><label>Produto<input id="ai-product" required maxlength="200" value="${esc(product?.name||"")}"></label><label>Características/benefícios<textarea id="ai-features" rows="3" maxlength="2000" placeholder="Informe apenas características verdadeiras"></textarea></label><div class="two-cols"><label>Preço<input id="ai-price" value="${product?.price!=null?esc(product.price):""}" placeholder="Ex.: R$ 49,90"></label><label>Canal<select id="ai-channel"><option>Instagram</option><option>WhatsApp</option><option>Facebook</option><option>Telegram</option></select></label></div><label>Link de afiliado<input id="ai-link" value="${esc(product?.source_url||"")}" placeholder="https://..."></label><label>Estilo<select id="ai-style"><option>Persuasivo</option><option>Direto</option><option>Descontraído</option><option>Informativo</option><option>Urgente</option></select></label><button class="primary" id="generate-btn">✦ Gerar conteúdo</button></form><div id="ai-result" class="result-box hidden"></div></div>`;$("ai-form").onsubmit=async e=>{e.preventDefault();const btn=$("generate-btn");btn.disabled=true;btn.textContent="Gerando...";try{const d=await api("/api/ai/generate",{method:"POST",body:JSON.stringify({kind:$("ai-kind").value,product_name:$("ai-product").value,features:$("ai-features").value,price:$("ai-price").value,link:$("ai-link").value,channel:$("ai-channel").value,style:$("ai-style").value})});$("ai-result").classList.remove("hidden");$("ai-result").innerHTML=`<div style="white-space:pre-wrap;line-height:1.7">${esc(d.content)}</div><button class="secondary" id="copy-ai" style="margin-top:12px">Copiar conteúdo</button>`;$("copy-ai").onclick=async()=>{await navigator.clipboard.writeText(d.content);toast("Conteúdo copiado.")};toast("Conteúdo gerado.")}catch(err){toast(err.message,true)}finally{btn.disabled=false;btn.textContent="✦ Gerar conteúdo"}};}

const scriptStyles = [
  "A.I.D.A.", "D.U.R.O.", "P.A.S.", "A.I.C.A.", "A.B.C.", "U.G.C.",
  "Problema → Solução", "Antes → Depois", "Quebra de Objeção",
  "Comparação → Alternativa", "Curiosidade → Revelação",
  "Descoberta → Demonstração → Benefício",
  "Desejo → Transformação → Ação", "Curiosidade e Descoberta",
  "Comparação e Contraste", "Identificação com o Público",
  "Quebra de Padrão", "Surpresa", "VTSD"
];

function renderScripts(){
  activateNav("scripts");
  if(state.user?.plan!=="premium"){
    $("view").innerHTML=`<div class="view-card"><h2>Roteiros</h2><p>Este módulo é exclusivo do plano Premium.</p><p class="muted">Faça upgrade para liberar a geração de roteiros por IA.</p><button class="primary" id="scripts-plans">Ver planos</button></div>`;
    $("scripts-plans").onclick=()=>renderView("plans");
    return;
  }
  $("view").innerHTML=`<div class="view-card"><h2>Roteiros com IA</h2><p class="muted">Crie roteiros para vídeos curtos com o estilo e a duração que preferir.</p>
  <form id="script-form">
  <label>Produto<input id="script-product" required maxlength="200" placeholder="Nome do produto"></label>
  <label>Características e benefícios verdadeiros<textarea id="script-features" rows="3" maxlength="2000" placeholder="O que o produto realmente oferece?"></textarea></label>
  <div class="two-cols">
  <label>Preço (opcional)<input id="script-price" maxlength="100" placeholder="Ex.: R$ 49,90"></label>
  <label>Canal<select id="script-channel"><option>TikTok</option><option>Instagram Reels</option><option>YouTube Shorts</option><option>Facebook</option><option>WhatsApp</option></select></label></div>
  <label>Estilo do roteiro<select id="script-style">${scriptStyles.map(s=>`<option>${esc(s)}</option>`).join("")}</select></label>
  <label>Duração<select id="script-duration"><option value="10">10 segundos</option><option value="15">15 segundos</option><option value="20">20 segundos</option><option value="30" selected>30 segundos</option><option value="45">45 segundos</option><option value="60">60 segundos (1 minuto)</option></select></label>
  <label>Link do produto (opcional)<input id="script-link" maxlength="2000" placeholder="https://..."></label>
  <button class="primary" id="script-generate" type="submit">Gerar roteiro</button></form>
  <div id="script-result" class="result-box hidden"></div></div>`;
  $("script-form").onsubmit=async e=>{
    e.preventDefault();
    const btn=$("script-generate");
    btn.disabled=true;btn.textContent="Gerando roteiro...";
    try{
      const d=await api("/api/ai/scripts",{method:"POST",body:JSON.stringify({
        product_name:$("script-product").value,
        features:$("script-features").value,
        price:$("script-price").value,
        link:$("script-link").value,
        channel:$("script-channel").value,
        style:$("script-style").value,
        duration:Number($("script-duration").value)
      })});
      const result=$("script-result");
      result.classList.remove("hidden");
      result.innerHTML=`<div style="white-space:pre-wrap;line-height:1.7">${esc(d.content)}</div><button class="secondary" id="copy-script" style="margin-top:12px">Copiar roteiro</button>`;
      $("copy-script").onclick=async()=>{await navigator.clipboard.writeText(d.content);toast("Roteiro copiado.")};
      toast("Roteiro gerado.");
    }catch(err){toast(err.message,true)}
    finally{btn.disabled=false;btn.textContent="Gerar roteiro"}
  };
}

function renderVideos(){
  activateNav("videos");
  if(state.user?.plan!=="premium"){
    $("view").innerHTML=`<div class="view-card"><h2>Criar vídeos</h2><p>Este módulo é exclusivo do plano Premium.</p><button class="primary" id="videos-plans">Ver planos</button></div>`;
    $("videos-plans").onclick=()=>renderView("plans");
    return;
  }
  $("view").innerHTML=`<div class="view-card"><h2>Criar vídeos</h2><p class="muted">Área de integração com o serviço Google Flow via useapi.net.</p><div class="notice">A conexão ainda precisa ser configurada. Esta tela não gera vídeos até que o serviço, a conta e as credenciais sejam integrados.</div><h3>Próximos passos</h3><p>Configure sua conta e credenciais no servidor, nunca no JavaScript do navegador. Depois será possível enviar um roteiro e solicitar a geração de vídeo.</p><p class="muted">Não coloque tokens ou chaves de API nesta página nem os compartilhe no chat.</p></div>`;
}

function renderSupport(){
  activateNav("support");
  $("view").innerHTML=`<div class="view-card"><h2>Suporte</h2><p class="muted">Área de ajuda do ShopPro.</p><h3>Como podemos ajudar?</h3><p>Descreva sua dúvida ou o problema que encontrou. O envio automático de solicitações ainda precisa ser conectado a um canal de atendimento.</p><label>Descrição<textarea id="support-message" rows="5" maxlength="3000" placeholder="Conte o que aconteceu..."></textarea></label><button class="secondary" id="copy-support">Copiar descrição</button><p class="muted">Este botão copia o texto para você enviar pelo canal de atendimento quando estiver disponível.</p></div>`;
  $("copy-support").onclick=async()=>{
    const value=$("support-message").value.trim();
    if(!value){toast("Escreva uma descrição primeiro.",true);return}
    try{await navigator.clipboard.writeText(value);toast("Descrição copiada.")}
    catch{toast("Não foi possível copiar automaticamente.",true)}
  };
}

function renderCalculator(product=null){activateNav("calculator");$("view").innerHTML=`<div class="view-card"><h2>Calculadora de comissões</h2><p class="muted">Calcule uma estimativa a partir do preço e do percentual informado. O valor real depende das regras da plataforma.</p><div class="calculator-row"><label>Preço do produto (R$)<input id="calc-price" type="number" min="0" step=".01" value="${product?.price??""}" placeholder="100,00"></label><label>Comissão (%)<input id="calc-percent" type="number" min="0" max="100" step=".01" value="${product?.commission_percent??""}" placeholder="10"></label></div><div class="result-box"><span>Comissão estimada por venda</span><strong id="calc-result">R$ 0,00</strong><small class="muted">Estimativa antes de ajustes, cancelamentos ou regras da plataforma.</small></div></div>`;const calc=()=>{$("calc-result").textContent=money((Number($("calc-price").value)||0)*(Number($("calc-percent").value)||0)/100)};$("calc-price").oninput=calc;$("calc-percent").oninput=calc;calc();}
async function renderHistory(){activateNav("history");const d=await api("/api/history");$("view").innerHTML=`<div class="view-card"><h2>Histórico de conteúdo</h2><p class="muted">Seu plano mantém o histórico por ${d.days} dias.</p><div class="simple-list" id="history-list"></div></div>`;$("history-list").innerHTML=d.history.map(x=>`<div class="list-row"><div><strong>${esc(x.product_name)}</strong><small>${esc(x.kind==="hashtags"?"Hashtags":"Texto")} · ${new Date(x.created_at).toLocaleString("pt-BR")}</small><p>${esc(x.content.slice(0,240))}${x.content.length>240?"…":""}</p></div><button class="secondary" data-hcopy="${x.id}">Copiar</button></div>`).join("")||"<p class='muted'>Nenhuma geração no período.</p>";d.history.forEach(x=>document.querySelector(`[data-hcopy="${x.id}"]`).onclick=async()=>{await navigator.clipboard.writeText(x.content);toast("Conteúdo copiado.")});}
async function renderAdmin(){activateNav("admin");if(state.user?.email?.trim().toLowerCase()!=="shoppro.suporte1@gmail.com"){toast("Acesso exclusivo ao administrador.",true);return renderView("radar")}$("view").innerHTML='<div class="view-card"><h2>Administração</h2><p>Gerencie os usuários e seus planos.</p><button class="primary" id="admin-refresh">Atualizar usuários</button><p id="admin-message"></p><div id="admin-users" class="simple-list"></div></div>';async function carregar(){const box=$("admin-users"),msg=$("admin-message");box.innerHTML="";msg.textContent="Carregando usuários...";try{const d=await api("/api/admin/users");msg.textContent="Total de usuários: "+d.users.length;box.innerHTML=d.users.map(u=>'<div class="list-row"><div><strong>'+esc(u.name||"Sem nome")+'</strong><small>'+esc(u.email)+'</small><small>Plano: '+esc(u.plan)+'</small></div><div><select data-plan="'+u.id+'">'+["free","starter","pro","premium"].map(p=>'<option value="'+p+'" '+(u.plan===p?"selected":"")+'>'+p.toUpperCase()+'</option>').join("")+'</select><button class="secondary" data-save="'+u.id+'">Salvar</button></div></div>').join("")||"Nenhum usuário cadastrado.";box.querySelectorAll("[data-save]").forEach(b=>b.onclick=async()=>{b.disabled=true;try{const id=b.dataset.save,p=box.querySelector('[data-plan="'+id+'"]').value;await api("/api/admin/users/"+id+"/plan?plan="+encodeURIComponent(p),{method:"POST"});toast("Plano atualizado.");await carregar()}catch(e){toast(e.message,true)}finally{b.disabled=false}})}catch(e){msg.textContent=e.message}}$("admin-refresh").onclick=carregar;await carregar()}
function renderPlans(){activateNav("plans");const plans=[["free","Free","Grátis",["Radar ilimitado","Comissão até 20%","5 textos e 5 gerações de hashtags/dia","20 links · 20 favoritos","Histórico de 7 dias"]],["starter","Starter","R$ 19,90/mês",["Radar ilimitado","Comissão até 25%","30 textos e 30 hashtags/dia","200 links · 200 favoritos","Histórico de 30 dias","Filtros e coleções adicionais"]],["pro","Pro","R$ 39,90/mês",["Radar ilimitado","Comissão até 30%","100 textos e 100 hashtags/dia","Links e favoritos sem limite comercial","Histórico de 90 dias","Rankings e comparação avançada"]],["premium","Premium","R$ 69,90/mês",["Radar ilimitado","Sem teto artificial de comissão","200 textos e 200 hashtags/dia","Radar de altas comissões","Histórico de 365 dias","Módulos exclusivos quando disponíveis"]]];$("view").innerHTML=`<div class="notice">Seu plano atual é ${esc(state.plan.name)}. A cobrança online ainda não está conectada nesta versão; mudanças de plano exigem integração de pagamento e confirmação no backend.</div><div class="plan-grid">${plans.map(p=>`<div class="plan-card ${p[0]==="pro"?"featured":""}"><h3>${p[1]}</h3><div class="plan-price">${p[2]}</div><ul>${p[3].map(x=>`<li>${x}</li>`).join("")}</ul><button class="${state.user.plan===p[0]?"secondary":"primary"}" ${state.user.plan===p[0]?"disabled":""}>${state.user.plan===p[0]?"Plano atual":"Ver detalhes"}</button></div>`).join("")}</div><p class="data-footnote">Limites técnicos e disponibilidade das fontes de dados podem afetar a atualização do radar. Nenhum plano garante vendas ou ganhos.</p>`;}
$("auth-form").onsubmit=async e=>{e.preventDefault();const body={email:$("auth-email").value,password:$("auth-password").value};if(state.authMode==="register")body.name=$("auth-name").value;try{const d=await api(state.authMode==="login"?"/api/auth/login":"/api/auth/register",{method:"POST",body:JSON.stringify(body)});state.token=d.token;localStorage.setItem("afp_token",d.token);state.user=d.user;const me=await api("/api/auth/me");state.plan=me.plan;showApp();await renderView("radar")}catch(err){$("auth-message").textContent=err.message}};
$("tab-login").onclick=()=>setAuthMode("login");$("tab-register").onclick=()=>setAuthMode("register");$("logout").onclick=()=>{logout();showAuth()};document.querySelectorAll(".nav[data-view]").forEach(b=>b.addEventListener("click",()=>{if(state.token)renderView(b.dataset.view)}));
$("product-form").onsubmit=async e=>{e.preventDefault();const num=id=>$(id).value===""?null:Number($(id).value);try{await api("/api/products",{method:"POST",body:JSON.stringify({name:$("p-name").value,image_url:$("p-image").value||null,price:num("p-price"),commission_percent:num("p-commission"),category:$("p-category").value||null,sales_count:num("p-sales"),trend_percent:num("p-trend"),source_url:$("p-url").value||null})});$("product-dialog").close();e.target.reset();toast("Produto cadastrado.");await renderView("radar")}catch(err){toast(err.message,true)}};
$("link-form").onsubmit=async e=>{e.preventDefault();try{await api("/api/links",{method:"POST",body:JSON.stringify({label:$("link-label").value,url:$("link-url").value})});$("link-dialog").close();toast("Link salvo.");if(state.currentView==="links")renderLinks()}catch(err){toast(err.message,true)}};
document.querySelectorAll("[data-close]").forEach(b=>b.onclick=()=>$(b.dataset.close).close());
setAuthMode("login");loadSession();
initializeGoogleLogin();

function corrigirRolagemSidebar() {
  const sidebar = document.querySelector(".sidebar");
  if (!sidebar) return;

  sidebar.style.setProperty("overflow-y", "auto", "important");
  sidebar.style.setProperty("overflow-x", "hidden", "important");

  const maxScroll = sidebar.scrollHeight - sidebar.clientHeight;
  sidebar.scrollTop = maxScroll > 0 ? maxScroll : 0;
}

corrigirRolagemSidebar();

window.addEventListener("load", corrigirRolagemSidebar);
window.addEventListener("resize", corrigirRolagemSidebar);
setTimeout(corrigirRolagemSidebar, 500);
setTimeout(corrigirRolagemSidebar, 1500);
