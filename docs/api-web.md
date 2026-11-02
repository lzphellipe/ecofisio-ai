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

## Endpoints

| Método | Rota | O que faz |
| --- | --- | --- |
| GET | `/saude` | status, nome do modelo e nº de trechos no índice |
| POST | `/perguntar` | corpo `{"pergunta": "..."}` → resposta auditada (resumo, entregues, bloqueadas, lacunas, buscas) + `id` |
| GET | `/historico?limite=50` | perguntas anteriores (id, pergunta, resumo, contagens) |
| GET | `/historico/{id}` | rastro completo de uma pergunta |

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

## Durante o desenvolvimento do front

Para iterar no front com recarga automática, rode os dois separados: o dev server em
`http://localhost:5173` e a API em `:8080`. Nesse modo, defina `VITE_API_URL=http://localhost:8080`
no `web/.env` (o CORS já libera a 5173). Se a API estiver na VM e o front no seu PC, faça o túnel
SSH da 8080 além da 8000. No build de produção, deixe `VITE_API_URL` vazio para o front chamar a
mesma origem.
