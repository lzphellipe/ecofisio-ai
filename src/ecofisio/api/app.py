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
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from ecofisio.agent.llm import LLMError, OpenAICompatibleChat
from ecofisio.agent.research import AgentError, ResearchAgent
from ecofisio.evidence.retraction import CrossrefClient, RetractionChecker, RetractionWatchIndex
from ecofisio.rag.index import LiteratureIndex

_RUN_ID = re.compile(r"^[0-9A-Za-z_-]+$")  # evita travessia de caminho em /historico/{id}


def _truthy(value: str | None) -> bool:
    return value not in (None, "", "0", "false", "False")


def build_agent_from_env() -> ResearchAgent:
    """Monta o agente a partir das variáveis de ambiente (espelha o build_agent do ecofisio-ask)."""
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
    model = OpenAICompatibleChat(
        os.environ.get("ECOFISIO_LLM_URL", "http://localhost:8000/v1"),
        os.environ.get("ECOFISIO_LLM_MODEL", "Qwen/Qwen3-8B"),
        api_key=os.environ.get("ECOFISIO_LLM_KEY"),
        extra_body={
            "chat_template_kwargs": {"enable_thinking": _truthy(os.environ.get("ECOFISIO_PENSAR"))}
        },
    )
    return ResearchAgent(
        model,
        index,
        checker,
        verifier,
        require_semantic=not _truthy(os.environ.get("ECOFISIO_SEM_VERIFICACAO")),
    )


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


def create_app(
    agent: ResearchAgent | None = None,
    *,
    runs_dir: Path | None = None,
    users: dict[str, str] | None = None,
    cors_origins: list[str] | None = None,
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
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.state.agent = agent or build_agent_from_env()

    security = HTTPBasic(auto_error=False)

    def auth(creds: HTTPBasicCredentials | None = Depends(security)) -> str:
        if not users:  # sem login configurado: libera (use só em rede confiável)
            return "anon"
        if (
            creds
            and creds.username in users
            and secrets.compare_digest(users[creds.username], creds.password)
        ):
            return creds.username
        raise HTTPException(401, "credenciais inválidas", {"WWW-Authenticate": "Basic"})

    @app.get("/saude")
    def saude(_: str = Depends(auth)) -> dict[str, Any]:
        ag: ResearchAgent = app.state.agent
        return {"status": "ok", "modelo": ag.model.name, "trechos": len(ag.index)}

    @app.post("/perguntar")
    def perguntar(req: Pergunta, _: str = Depends(auth)) -> dict[str, Any]:
        try:
            answer = app.state.agent.ask(req.pergunta)
        except (LLMError, AgentError) as exc:
            raise HTTPException(502, f"erro do modelo: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        data = answer.to_dict()
        runs.mkdir(parents=True, exist_ok=True)
        rid = f"{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}"
        (runs / f"{rid}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        data["id"] = rid
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
        return json.loads(f.read_text("utf-8"))

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
