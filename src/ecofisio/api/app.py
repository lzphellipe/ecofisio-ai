"""API HTTP do assistente de pesquisa, para o front React.

Fina de propósito: envolve o ResearchAgent (o mesmo motor do ecofisio-ask) e devolve a resposta
já auditada (entregues, bloqueadas, lacunas, buscas). Roda na mesma VM que o vLLM; quando o Brev
está ligado, a API sobe junto.

Configuração por variáveis de ambiente (as mesmas do ecofisio-ask, mais as da API):
    ECOFISIO_LLM_URL        (padrão http://localhost:8000/v1)
    ECOFISIO_LLM_MODEL      (padrão Qwen/Qwen3-8B)
    ECOFISIO_LLM_KEY        chave do servidor vLLM
    ECOFISIO_INDEX          (padrão data/processed/literature)
    ECOFISIO_CROSSREF_EMAIL e/ou ECOFISIO_RW_CSV  (obrigatório um: sem retratação, nada é entregue)
    ECOFISIO_NLI_MODEL      modelo do verificador semântico (opcional)
    ECOFISIO_SEM_VERIFICACAO=1  entrega sem verificação semântica (como --sem-verificacao-semantica)
    ECOFISIO_PENSAR=1       liga o modo de raciocínio do Qwen 3
    ECOFISIO_RUNS           pasta dos rastros/histórico (padrão runs)
    ECOFISIO_API_USERS      "user1:senha1,user2:senha2" (vazio = sem login; só em rede confiável)
    ECOFISIO_API_CORS       origens permitidas, separadas por vírgula (padrão http://localhost:5173)
    ECOFISIO_API_HOST/PORT  (padrão 0.0.0.0:8080)
    GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET   liga o "Entrar com Google" (opcional)
    GOOGLE_OAUTH_REDIRECT   URL de callback (padrão http://localhost:8080/auth/google/callback)
    ECOFISIO_SESSION_SECRET segredo para assinar o cookie de sessão (fixe um valor aleatório)
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ecofisio.agent.anthropic_chat import AnthropicChat
from ecofisio.agent.especialistas import especialistas, foco_de
from ecofisio.agent.llm import LLMError, OpenAICompatibleChat
from ecofisio.agent.providers import provedores
from ecofisio.agent.research import AgentError, ResearchAgent
from ecofisio.api.google_auth import GoogleOAuth, OAuthError
from ecofisio.api.store import AppStore
from ecofisio.evidence.retraction import CrossrefClient, RetractionChecker, RetractionWatchIndex
from ecofisio.rag.index import LiteratureIndex

_RUN_ID = re.compile(r"^[0-9A-Za-z_-]+$")  # evita travessia de caminho em /historico/{id}
_COOKIE_SESSAO = "eco_sessao"
_COOKIE_STATE = "eco_oauth_state"


def _truthy(value: str | None) -> bool:
    return value not in (None, "", "0", "false", "False")


def build_agentes_from_env() -> dict[str, ResearchAgent]:
    """Um agente por provedor de modelo ativo (índice/auditor compartilhados). Chave por env."""
    index = LiteratureIndex.load(
        Path(os.environ.get("ECOFISIO_INDEX", "data/processed/literature"))
    )
    email = os.environ.get("ECOFISIO_CROSSREF_EMAIL")
    rw = os.environ.get("ECOFISIO_RW_CSV")
    if not email and not rw:
        raise RuntimeError(
            "defina ECOFISIO_CROSSREF_EMAIL e/ou ECOFISIO_RW_CSV: "
            "sem checagem de retratação, nada é entregue"
        )
    checker = RetractionChecker(
        index=RetractionWatchIndex.from_csv(Path(rw)) if rw else None,
        client=CrossrefClient(mailto=email) if email else None,
    )
    verifier = None
    if nli := os.environ.get("ECOFISIO_NLI_MODEL"):
        from ecofisio.evidence.verify import NLIVerifier

        verifier = NLIVerifier(nli)
    require_semantic = not _truthy(os.environ.get("ECOFISIO_SEM_VERIFICACAO"))
    pensar = _truthy(os.environ.get("ECOFISIO_PENSAR"))

    agentes: dict[str, ResearchAgent] = {}
    for prov in provedores():
        if prov.kind == "anthropic":
            model = AnthropicChat(prov.base_url, prov.model, api_key=prov.api_key)
        else:
            # enable_thinking é específico do Qwen no vLLM; não enviar aos endpoints hospedados
            extra = (
                {"chat_template_kwargs": {"enable_thinking": pensar}} if prov.id == "qwen" else {}
            )
            model = OpenAICompatibleChat(
                prov.base_url, prov.model, api_key=prov.api_key, extra_body=extra
            )
        agentes[prov.id] = ResearchAgent(
            model, index, checker, verifier, require_semantic=require_semantic
        )
    return agentes


def _parse_users(raw: str | None) -> dict[str, str]:
    users: dict[str, str] = {}
    for part in (raw or "").split(","):
        if ":" in part:
            u, p = part.split(":", 1)
            if u.strip():
                users[u.strip()] = p
    return users


class Pergunta(BaseModel):
    pergunta: str = Field(min_length=1, max_length=2000)
    modelo: str | None = None  # id do provedor (qwen, gemini, openai); padrão: o primeiro
    especialista: str | None = None  # lente de foco (celular, bioquimica, ...); padrão: geral


class NovoProjeto(BaseModel):
    nome: str = Field(min_length=1, max_length=120)


class AddPergunta(BaseModel):
    pergunta_id: str = Field(min_length=1, max_length=64)


class NovoArtefato(BaseModel):
    pergunta_id: str = Field(min_length=1, max_length=64)
    nome: str = Field(default="", max_length=120)


def create_app(
    agent: ResearchAgent | None = None,
    *,
    agentes: dict[str, ResearchAgent] | None = None,
    runs_dir: Path | None = None,
    store: AppStore | None = None,
    users: dict[str, str] | None = None,
    cors_origins: list[str] | None = None,
    front_dir: Path | None = None,
    oauth: GoogleOAuth | None = None,
) -> FastAPI:
    app = FastAPI(
        title="ecofisio-ai",
        description="Assistente de pesquisa em biologia com citação verificável",
    )
    runs = runs_dir or Path(os.environ.get("ECOFISIO_RUNS", "runs"))
    users = users if users is not None else _parse_users(os.environ.get("ECOFISIO_API_USERS"))
    origins = cors_origins or [
        o.strip()
        for o in os.environ.get("ECOFISIO_API_CORS", "http://localhost:5173").split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )
    if agentes is None:
        agentes = {"qwen": agent} if agent is not None else build_agentes_from_env()
    if not agentes:
        raise RuntimeError("nenhum provedor de modelo disponível")
    app.state.agentes = agentes
    app.state.modelo_padrao = next(iter(agentes))
    loja = store or AppStore(Path(os.environ.get("ECOFISIO_STORE", "data/app")))
    oauth = oauth if oauth is not None else GoogleOAuth.from_env()
    app.state.oauth = oauth

    def resumo_run(rid: str) -> dict[str, Any] | None:
        """Item de histórico (id, pergunta, resumo, contagens) a partir do rastro, ou None."""
        f = runs / f"{rid}.json"
        if not _RUN_ID.match(rid) or not f.is_file():
            return None
        try:
            d = json.loads(f.read_text("utf-8"))
        except (ValueError, OSError):
            return None
        return {
            "id": rid,
            "pergunta": d.get("pergunta"),
            "criado_em": d.get("criado_em"),
            "resumo": d.get("resumo"),
            "entregues": len(d.get("entregues") or []),
            "bloqueadas": len(d.get("bloqueadas") or []),
        }

    security = HTTPBasic(auto_error=False)

    def auth(request: Request, creds: HTTPBasicCredentials | None = Depends(security)) -> str:
        # 1) sessão Google (cookie assinado) tem prioridade quando o login está configurado
        if oauth is not None:
            sessao = oauth.ler_sessao(request.cookies.get(_COOKIE_SESSAO))
            if sessao:
                return str(sessao.get("email") or sessao.get("sub") or "google")
        # 2) Basic auth (fallback para dev/local ou quando não há login Google)
        if users and creds and creds.username in users:
            if secrets.compare_digest(users[creds.username], creds.password):
                return creds.username
        # 3) sem nenhum login configurado: libera (use só em rede confiável)
        if not users and oauth is None:
            return "anon"
        raise HTTPException(401, "não autenticado", {"WWW-Authenticate": "Basic"})

    def _rotulos() -> dict[str, str]:
        return {p.id: p.label for p in provedores()}

    # ---- login com Google (OAuth2) --------------------------------------------------------
    @app.get("/auth/me")
    def auth_me(request: Request) -> dict[str, Any]:
        """Quem está logado (ou não), e se o login Google está disponível no servidor."""
        login_google = oauth is not None
        if oauth is not None:
            sessao = oauth.ler_sessao(request.cookies.get(_COOKIE_SESSAO))
            if sessao:
                return {
                    "autenticado": True,
                    "usuario": {"email": sessao.get("email"), "nome": sessao.get("nome")},
                    "login_google": True,
                }
        # Basic auth não deixa o front saber "quem" sem desafiar; só reportamos o estado do Google
        return {"autenticado": False, "usuario": None, "login_google": login_google}

    @app.get("/auth/google/login")
    def auth_google_login() -> RedirectResponse:
        if oauth is None:
            raise HTTPException(503, "login com Google não configurado no servidor")
        state = secrets.token_urlsafe(24)
        resp = RedirectResponse(oauth.authorization_url(state), status_code=302)
        # guarda o state num cookie curto para conferir no callback (proteção CSRF)
        resp.set_cookie(
            _COOKIE_STATE, state, max_age=600, httponly=True, samesite="lax", path="/auth"
        )
        return resp

    @app.get("/auth/google/callback")
    def auth_google_callback(
        request: Request, code: str | None = None, state: str | None = None
    ) -> RedirectResponse:
        if oauth is None:
            raise HTTPException(503, "login com Google não configurado no servidor")
        esperado = request.cookies.get(_COOKIE_STATE)
        if not code or not state or not esperado or not secrets.compare_digest(state, esperado):
            raise HTTPException(400, "state inválido ou code ausente no callback do Google")
        try:
            claims = oauth.exchange_code(code)
        except OAuthError as exc:
            raise HTTPException(502, f"falha no login com Google: {exc}") from exc
        email = str(claims.get("email") or "")
        if not email or not claims.get("email_verified", True):
            raise HTTPException(403, "conta Google sem e-mail verificado")
        token = oauth.emitir_sessao(
            email=email, nome=str(claims.get("name") or email), sub=str(claims.get("sub") or "")
        )
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie(
            _COOKIE_SESSAO,
            token,
            max_age=oauth.session_horas * 3600,
            httponly=True,
            samesite="lax",
            path="/",
        )
        resp.delete_cookie(_COOKIE_STATE, path="/auth")
        return resp

    @app.post("/auth/logout")
    def auth_logout(response: Response) -> dict[str, bool]:
        response.delete_cookie(_COOKIE_SESSAO, path="/")
        return {"ok": True}

    @app.get("/saude")
    def saude(_: str = Depends(auth)) -> dict[str, Any]:
        padrao: ResearchAgent = app.state.agentes[app.state.modelo_padrao]
        return {"status": "ok", "modelo": padrao.model.name, "trechos": len(padrao.index)}

    @app.get("/modelos")
    def modelos(_: str = Depends(auth)) -> dict[str, Any]:
        rot = _rotulos()
        lista = [
            {"id": mid, "label": rot.get(mid, mid), "modelo": ag.model.name}
            for mid, ag in app.state.agentes.items()
        ]
        return {"padrao": app.state.modelo_padrao, "modelos": lista}

    @app.get("/especialistas")
    def listar_especialistas(_: str = Depends(auth)) -> list[dict[str, str]]:
        return [{"id": e.id, "label": e.label} for e in especialistas()]

    @app.post("/perguntar")
    def perguntar(req: Pergunta, _: str = Depends(auth)) -> dict[str, Any]:
        mid = req.modelo or app.state.modelo_padrao
        agente = app.state.agentes.get(mid)
        if agente is None:
            raise HTTPException(400, f"modelo desconhecido: {mid}")
        try:
            answer = agente.ask(req.pergunta, foco=foco_de(req.especialista))
        except (LLMError, AgentError) as exc:
            raise HTTPException(502, f"erro do modelo: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        data = answer.to_dict()
        runs.mkdir(parents=True, exist_ok=True)
        rid = f"{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}"
        data["id"] = rid  # grava o id dentro do rastro também, para o histórico devolvê-lo
        (runs / f"{rid}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        return data

    @app.get("/historico")
    def historico(_: str = Depends(auth), limite: int = 50) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for f in sorted(runs.glob("*.json"), reverse=True)[: max(1, min(limite, 500))]:
            try:
                d = json.loads(f.read_text("utf-8"))
            except (ValueError, OSError):
                continue
            out.append(
                {
                    "id": f.stem,
                    "pergunta": d.get("pergunta"),
                    "criado_em": d.get("criado_em"),
                    "resumo": d.get("resumo"),
                    "entregues": len(d.get("entregues") or []),
                    "bloqueadas": len(d.get("bloqueadas") or []),
                }
            )
        return out

    @app.get("/historico/{rid}")
    def historico_item(rid: str, _: str = Depends(auth)) -> dict[str, Any]:
        if not _RUN_ID.match(rid):
            raise HTTPException(400, "id inválido")
        f = runs / f"{rid}.json"
        if not f.is_file():
            raise HTTPException(404, "não encontrado")
        d = json.loads(f.read_text("utf-8"))
        d.setdefault("id", rid)  # rastros antigos não gravavam o id
        return d

    @app.get("/buscar")
    def buscar(
        q: str, k: int = 8, so_primarios: bool = False, _: str = Depends(auth)
    ) -> dict[str, Any]:
        """Busca direta no corpus, sem LLM (como o ecofisio-busca): trechos para o usuário ler."""
        q = q.strip()
        if not q:
            raise HTTPException(400, "consulta vazia")
        ag: ResearchAgent = app.state.agentes[app.state.modelo_padrao]
        k = max(1, min(k, 20))
        mode = "hybrid" if ag.index.embedder else "lexical"
        hits = ag.index.search(q, k=k * 5 if so_primarios else k, mode=mode)
        if so_primarios:
            hits = [h for h in hits if h.passage.primary_evidence][:k]
        else:
            hits = hits[:k]
        return {"consulta": q, "resultados": [h.as_tool_result() for h in hits]}

    # ---- projetos (agrupar perguntas por tema) ----
    @app.get("/projetos")
    def listar_projetos(_: str = Depends(auth)) -> list[dict[str, Any]]:
        return [
            {
                "id": p["id"],
                "nome": p["nome"],
                "criado_em": p["criado_em"],
                "n": len(p["perguntas"]),
            }
            for p in loja.projetos()
        ]

    @app.post("/projetos")
    def criar_projeto(req: NovoProjeto, _: str = Depends(auth)) -> dict[str, Any]:
        return loja.criar_projeto(req.nome.strip())

    @app.get("/projetos/{pid}")
    def obter_projeto(pid: str, _: str = Depends(auth)) -> dict[str, Any]:
        proj = loja.projeto(pid)
        if proj is None:
            raise HTTPException(404, "projeto não encontrado")
        perguntas = [r for rid in proj["perguntas"] if (r := resumo_run(rid)) is not None]
        return {**proj, "perguntas": perguntas}

    @app.delete("/projetos/{pid}")
    def excluir_projeto(pid: str, _: str = Depends(auth)) -> dict[str, bool]:
        if not loja.excluir_projeto(pid):
            raise HTTPException(404, "projeto não encontrado")
        return {"ok": True}

    @app.post("/projetos/{pid}/perguntas")
    def add_pergunta(pid: str, req: AddPergunta, _: str = Depends(auth)) -> dict[str, Any]:
        if resumo_run(req.pergunta_id) is None:
            raise HTTPException(404, "pergunta não encontrada")
        proj = loja.adicionar_pergunta(pid, req.pergunta_id)
        if proj is None:
            raise HTTPException(404, "projeto não encontrado")
        return {"id": proj["id"], "nome": proj["nome"], "n": len(proj["perguntas"])}

    # ---- artefatos (respostas salvas) ----
    @app.get("/artefatos")
    def listar_artefatos(_: str = Depends(auth)) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for a in loja.artefatos():
            r = resumo_run(a["pergunta_id"])
            out.append({**a, "pergunta": r["pergunta"] if r else None, "existe": r is not None})
        return out

    @app.post("/artefatos")
    def criar_artefato(req: NovoArtefato, _: str = Depends(auth)) -> dict[str, Any]:
        r = resumo_run(req.pergunta_id)
        if r is None:
            raise HTTPException(404, "pergunta não encontrada")
        nome = req.nome.strip() or (r["pergunta"] or "Artefato")
        return loja.criar_artefato(req.pergunta_id, nome)

    @app.delete("/artefatos/{aid}")
    def excluir_artefato(aid: str, _: str = Depends(auth)) -> dict[str, bool]:
        if not loja.excluir_artefato(aid):
            raise HTTPException(404, "artefato não encontrado")
        return {"ok": True}

    # Serve o front compilado (web/dist), se existir: tudo num endereço só.
    # Montado por último, para as rotas da API acima terem prioridade.
    front = front_dir or Path(os.environ.get("ECOFISIO_FRONT", "web/dist"))
    if (front / "index.html").is_file():
        app.mount("/", StaticFiles(directory=front, html=True), name="front")

    return app


def main() -> None:
    import uvicorn

    host = os.environ.get("ECOFISIO_API_HOST", "0.0.0.0")  # noqa: S104 - exposto via HTTP Port do Brev
    port = int(os.environ.get("ECOFISIO_API_PORT", "8080"))
    if host == "0.0.0.0" and not _parse_users(os.environ.get("ECOFISIO_API_USERS")):  # noqa: S104
        print(
            "AVISO: API em 0.0.0.0 sem ECOFISIO_API_USERS (sem login). "
            "Defina usuários ou exponha só atrás do login do HTTP Port do Brev."
        )
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
