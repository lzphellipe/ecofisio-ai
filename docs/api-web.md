# API HTTP (backend do front React)

Camada fina de FastAPI sobre o `ResearchAgent` — a mesma lógica do `ecofisio-ask`, exposta por
HTTP para o front. Roda na VM do Brev, ao lado do vLLM; quando o Brev está ligado, a API sobe junto.

## Subir

Com o vLLM já no ar (`scripts/brev_serve.sh`), num outro terminal da VM:

```bash
cd /opt/ecofisio-ai && source .venv/bin/activate
pip install -e ".[api]"            # fastapi + uvicorn (uma vez)

export ECOFISIO_LLM_KEY="<chave do vLLM>"
export ECOFISIO_CROSSREF_EMAIL="voce@exemplo.org"
export ECOFISIO_SEM_VERIFICACAO=1              # enquanto não há modelo NLI
export ECOFISIO_API_USERS="luiz:senha1,thaysa:senha2"   # login leve (dois usuários)
ecofisio-api                                    # sobe em 0.0.0.0:8080
```

Exponha a porta **8080** pelo recurso **HTTP Port** do Brev e mande o link para a Thaysa. O login
do HTTP Port (conta Brev) protege o acesso; o `ECOFISIO_API_USERS` é uma segunda camada e separa
o histórico por usuário no front. Sem `ECOFISIO_API_USERS` a API fica **sem login** — só use assim
em rede confiável.

## Escolher o modelo (roteamento entre provedores)

O assistente pode usar vários modelos; o front mostra um seletor quando há mais de um. Cada
provedor é um endpoint compatível com a API da OpenAI e só aparece quando a **chave dele** está
definida como variável de ambiente (a chave nunca vai na URL nem no código):

| Provedor | Como ativar | Observação |
| --- | --- | --- |
| Qwen local (vLLM) | sempre ativo (`ECOFISIO_LLM_*`) | na sua GPU |
| Google Gemini Flash | `GEMINI_API_KEY` (chave do Google AI Studio) | econômico; modelo em `GEMINI_MODEL` (padrão `gemini-2.0-flash`) |
| Google Gemini Pro | `GEMINI_API_KEY` (a mesma chave) | mais forte; modelo em `GEMINI_MODEL_PRO` (padrão `gemini-2.5-pro`; `""` desativa) |
| OpenAI | `OPENAI_API_KEY` | API paga; modelo em `OPENAI_MODEL` (padrão `gpt-4o-mini`) |
| Anthropic Claude | `ANTHROPIC_API_KEY` | API paga; modelo em `ANTHROPIC_MODEL` (padrão `claude-sonnet-5-5`) |

```bash
export GEMINI_API_KEY="..."         # ativa o Gemini no seletor
# export OPENAI_API_KEY="..."       # ativa a OpenAI
# export ANTHROPIC_API_KEY="..."    # ativa o Claude
ecofisio-api
```

`GET /modelos` lista os provedores ativos; `POST /perguntar` aceita `"modelo": "<id>"` (ex.: `gemini`,
`claude`). Importante: isso usa a **API** de cada provedor, cobrada por uso com chave própria —
**não** a assinatura do app de chat (Gemini Advanced, ChatGPT Plus, Claude Pro), que não dá acesso
programático. O **Claude** não é compatível com a API da OpenAI: ele entra por um adaptador próprio
(`AnthropicChat`, formato Messages) que traduz histórico e ferramentas nos dois sentidos.

### Camada gratuita × paga (realidade por provedor)

- **Google** é o único com **API gratuita** de verdade (Google AI Studio, com limites de uso).
  Gratuito × pago é a **mesma chave/endpoint**: muda só o **faturamento (billing)** do projeto no
  Google (sobe limites e altera os termos de uso dos dados), não a config aqui. As entradas Flash e
  Pro no seletor usam a mesma `GEMINI_API_KEY` — a diferença é o **modelo**. O
  **Gemini Enterprise** que a universidade assina costuma ser o **app** do Gemini no Workspace —
  isso **não** é a mesma coisa que acesso programático. API da organização se dá pelo **Vertex AI**
  (projeto do Google Cloud da universidade, com autenticação própria), não por uma chave do AI
  Studio. Confirme com a TI se há Vertex AI habilitado antes de contar com ele.
- **Anthropic** e **OpenAI** não têm camada gratuita de API — só paga, por uso.

## Endpoints

| Método | Rota | O que faz |
| --- | --- | --- |
| GET | `/saude` | status, nome do modelo e nº de trechos no índice |
| POST | `/perguntar` | corpo `{"pergunta": "..."}` → resposta auditada (resumo, entregues, bloqueadas, lacunas, buscas) + `id` |
| GET | `/historico?limite=50` | perguntas anteriores (id, pergunta, resumo, contagens) |
| GET | `/historico/{id}` | rastro completo de uma pergunta |
| GET | `/auth/me` | quem está logado e se o login Google está disponível no servidor |
| GET | `/auth/google/login` | inicia o OAuth (redireciona para o Google) |
| GET | `/auth/google/callback` | retorno do Google: emite o cookie de sessão e manda para `/` |
| POST | `/auth/logout` | limpa o cookie de sessão |

Cada pergunta é gravada em `runs/*.json` (o disco da VM persiste entre liga/desliga), então o
histórico sobrevive às sessões sem precisar de banco.

## Variáveis de ambiente

As mesmas do `ecofisio-ask` (`ECOFISIO_LLM_URL/MODEL/KEY`, `ECOFISIO_INDEX`,
`ECOFISIO_CROSSREF_EMAIL`/`ECOFISIO_RW_CSV`, `ECOFISIO_NLI_MODEL`, `ECOFISIO_SEM_VERIFICACAO`,
`ECOFISIO_PENSAR`) mais as da API: `ECOFISIO_RUNS`, `ECOFISIO_API_USERS`, `ECOFISIO_API_CORS`
(padrão `http://localhost:5173`, a origem do dev server do React), `ECOFISIO_API_HOST`/`PORT`.

## Servir tudo num endereço só (API + front integrados)

Para a Thaysa abrir **uma URL** (sem dev server nem túnel de duas portas), o backend serve o front
compilado. Na VM, com o projeto atualizado:

```bash
cd web && npm install && npm run build   # gera web/dist (front chama a mesma origem)
cd .. && ecofisio-api                      # serve a API e o web/dist juntos, em :8080
```

A API procura `web/dist` (ou `ECOFISIO_FRONT`) e, se existir, serve o front na raiz — as rotas da
API (`/perguntar`, `/buscar`, `/projetos`…) têm prioridade. Exponha só a porta **8080** pelo HTTP
Port do Brev e pronto.

> Build precisa de Node na VM. Se ela não tiver, instale (`curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash - && sudo apt-get install -y nodejs`) ou compile no seu PC e copie `web/dist` para a VM.

## Login com Google (OAuth2)

O "Entrar com Google" diz **quem** é o usuário (identidade do app) — **não** dá acesso a nenhuma
LLM. As chaves dos provedores continuam sendo configuração do servidor. É opcional e *config-gated*:
sem `GOOGLE_OAUTH_CLIENT_ID`, o login fica desligado e o app segue no Basic auth (`ECOFISIO_API_USERS`).
Qualquer conta Google pode entrar (sem restrição de domínio — decisão do projeto).

**Como o fluxo funciona:** o front chama `GET /auth/me` para saber se o login Google está ligado e
mostra o botão; o botão vai para `/auth/google/login`, que redireciona ao Google; o Google volta em
`/auth/google/callback`, o servidor troca o `code` por tokens, lê o e-mail/nome do `id_token` e emite
um **cookie de sessão assinado por HMAC** (`eco_sessao`, `httponly`, validade em `ECOFISIO_SESSION_HORAS`,
padrão 12h). A cada requisição, a API valida esse cookie (ou o Basic auth, como alternativa).

**O que VOCÊ precisa criar** (uma vez, no Google Cloud Console):

1. Crie/escolha um projeto em [console.cloud.google.com](https://console.cloud.google.com).
2. *APIs & Services → OAuth consent screen*: tipo **External**, preencha nome do app e e-mail de
   suporte. Enquanto estiver em "Testing", adicione os e-mails de teste (ex.: o seu e o da Thaysa);
   para liberar a qualquer conta, publique o app.
3. *APIs & Services → Credentials → Create credentials → OAuth client ID*: tipo **Web application**.
   Em **Authorized redirect URIs**, coloque a URL de callback exatamente como o app vai expô-la, ex.:
   `http://localhost:8080/auth/google/callback` (dev) e a URL pública do Brev/servidor em produção.
4. Copie o **Client ID** e o **Client secret**.

**Como ligar no servidor** (nunca no código nem na URL — só variáveis de ambiente):

```bash
export GOOGLE_OAUTH_CLIENT_ID="...apps.googleusercontent.com"
export GOOGLE_OAUTH_CLIENT_SECRET="..."
export GOOGLE_OAUTH_REDIRECT="http://localhost:8080/auth/google/callback"  # = o redirect URI cadastrado
export ECOFISIO_SESSION_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"  # fixe este valor
ecofisio-api
```

Se o `ECOFISIO_SESSION_SECRET` mudar a cada boot, as sessões abertas são invalidadas (o usuário só
reloga). Em produção, sirva por **HTTPS** para o cookie viajar com segurança.

## Durante o desenvolvimento do front

Para iterar no front com recarga automática, rode os dois separados: o dev server em
`http://localhost:5173` e a API em `:8080`. Nesse modo, defina `VITE_API_URL=http://localhost:8080`
no `web/.env` (o CORS já libera a 5173). Se a API estiver na VM e o front no seu PC, faça o túnel
SSH da 8080 além da 8000. No build de produção, deixe `VITE_API_URL` vazio para o front chamar a
mesma origem.
