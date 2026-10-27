# AfiliadoPro — projeto inicial funcional

Projeto inicial para abrir no VS Code, com frontend responsivo e API FastAPI.

## O que já funciona
- Cadastro e login com senha armazenada usando PBKDF2 e token JWT.
- Planos Free, Starter, Pro e Premium configurados no backend.
- Radar de produtos ilimitado em todos os planos, com filtros e ordenação.
- Limite máximo de comissão por plano aplicado no backend: Free 20%, Starter 25%, Pro 30%, Premium sem teto artificial. O Radar não tem limite de quantidade de produtos em nenhum plano.
- Cadastro manual de produtos e importação CSV.
- Favoritos e gerenciador de links por usuário.
- Calculadora de comissão.
- Histórico e cotas de gerações de textos/hashtags.
- Integração opcional com Gemini, por variável de ambiente.
- Mensagens honestas quando a base não possui produtos.

## Requisitos
- Python 3.10 ou superior (recomendado Python 3.11+).
- Internet apenas para instalar dependências e chamar a IA quando configurada.

## Executar no Windows / VS Code

Abra o terminal nesta pasta do projeto e execute:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Abra `.env` e altere `APP_SECRET` e `ADMIN_KEY` para valores secretos próprios. Não compartilhe esse arquivo nem envie chaves para o chat. O banco SQLite local é criado automaticamente.

Inicie o servidor:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app:app --reload
```

Acesse http://127.0.0.1:8000

Documentação da API: http://127.0.0.1:8000/docs

## Usar IA (opcional)
1. Crie uma chave no Google AI Studio.
2. Cole-a em `GEMINI_API_KEY` dentro de `.env`.
3. Reinicie o servidor.

A disponibilidade e o uso gratuito dependem dos limites e condições atuais do Google. Se a chave não estiver configurada, o restante do site continua funcionando e a área de IA informa que precisa ser configurada.

## Importar produtos via CSV
No Radar, clique em **Importar CSV**. Use CSV UTF-8 com cabeçalho `name` e, opcionalmente, as colunas:

`name,image_url,price,category,commission_percent,sales_count,sales_period,trend_percent,source_url`

Exemplo de linha (use apenas dados reais):
`Fone Bluetooth,https://exemplo.com/imagem.jpg,89.90,Eletrônicos,12,250,últimos 30 dias,8.5,https://exemplo.com/produto`

Produtos importados por um usuário ficam vinculados a esse usuário. Não são apresentados como dados oficiais da Shopee.

## Planos pagos e produção — limitações importantes
- Os preços e recursos dos planos estão definidos, mas **não há gateway de pagamento conectado**. Não publique cobrança nem libere upgrade pago antes de integrar um provedor de pagamento e validar o status da assinatura no backend.
- O endpoint administrativo para ajustar plano é `POST /api/admin/users/{user_id}/plan?plan=starter` e exige o cabeçalho `X-Admin-Key` igual ao `ADMIN_KEY` do `.env`. Use apenas em ambiente confiável.
- Não existe integração oficial da Shopee neste projeto inicial. O Radar usa produtos cadastrados manualmente ou importados por CSV. Para dados automáticos, links de afiliado e download de vídeos, implemente e valide uma integração autorizada; não simule esses dados.
- Configure HTTPS, segredos fortes, backups, logs, rate limiting e um banco adequado antes de produção.
- Este starter é uma base funcional para desenvolvimento, não uma plataforma auditada para receber pagamentos em produção.

## Estrutura
- `app.py`: API, autenticação, banco SQLite, regras de planos e endpoints.
- `static/index.html`: estrutura da interface.
- `static/styles.css`: visual responsivo.
- `static/app.js`: interações da interface.
- `.env.example`: exemplo de configurações sem segredos reais.

## Integração com Shopee Affiliate Open API

1. Copie `.env.example` para `.env` na pasta `AfiliadoPro`.
2. Preencha `SHOPEE_APP_ID` e `SHOPEE_APP_SECRET` com as credenciais da Open API. Nunca coloque o Secret no JavaScript ou no HTML.
3. Instale as dependências com `py -m pip install -r requirements.txt`.
4. Reinicie o servidor com `py -m uvicorn app:app --reload`.
5. Entre no AfiliadoPro, abra o Radar, digite um termo no campo “Buscar produto” e clique em “Buscar na Shopee”.

A integração usa `productOfferV2` e assinatura SHA-256 no backend. Os produtos retornados são armazenados no catálogo compartilhado local para aparecerem no Radar e poderem ser favoritados. O catálogo depende dos dados e permissões que a Shopee liberar para sua aplicação; limites de chamadas também podem se aplicar. Não foi possível validar uma chamada real sem suas credenciais, então faça o primeiro teste e confira a mensagem retornada pela API.

Se aparecer erro 10020, confira App ID, Secret e horário do computador/servidor. Erro 10035 normalmente indica falta de permissão para a operação solicitada. Consulte a documentação da Shopee Affiliate Open API para confirmar o esquema GraphQL vigente.
