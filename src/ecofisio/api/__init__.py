"""API HTTP (FastAPI) do assistente: expõe o ResearchAgent para o front React."""

from ecofisio.api.app import build_agentes_from_env, create_app

__all__ = ["build_agentes_from_env", "create_app"]
