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

## Durante o desenvolvimento do front

Com o dev server do React em `http://localhost:5173`, o CORS já libera essa origem por padrão.
Aponte o front para `http://localhost:8080` (ou, se estiver no seu PC, faça o túnel SSH da 8080
além da 8000).
