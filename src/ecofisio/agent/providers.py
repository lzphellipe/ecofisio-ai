"""Provedores de modelo disponíveis para o assistente (roteamento — requisito 8 do plano).

Cada provedor é um endpoint compatível com a API da OpenAI, então o mesmo OpenAICompatibleChat
serve a todos trocando base_url/model/chave:

- qwen: o modelo local servido por vLLM na GPU (padrão; "grátis" = sua GPU).
- gemini: Google Gemini pelo endpoint compatível com OpenAI (chave do Google AI Studio; tem
  camada gratuita). Ativa só se GEMINI_API_KEY estiver definido.
- openai: API da OpenAI (paga). Ativa só se OPENAI_API_KEY estiver definido.

Claude (Anthropic) não é compatível com OpenAI e precisa de um adaptador próprio — fica para depois.
A chave de cada provedor vem de variável de ambiente; nunca da linha de comando nem do código.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Provedor:
    id: str
    label: str
    base_url: str
    model: str
    api_key_env: str

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env)


def provedores() -> list[Provedor]:
    """Provedores ativos: o local sempre, os hospedados só quando a chave está definida."""
    lista = [
        Provedor(
            id="qwen",
            label="Qwen local (vLLM)",
            base_url=os.environ.get("ECOFISIO_LLM_URL", "http://localhost:8000/v1"),
            model=os.environ.get("ECOFISIO_LLM_MODEL", "Qwen/Qwen3-8B"),
            api_key_env="ECOFISIO_LLM_KEY",
        )
    ]
    if os.environ.get("GEMINI_API_KEY"):
        lista.append(
            Provedor(
                id="gemini",
                label="Google Gemini",
                base_url=os.environ.get(
                    "GEMINI_BASE_URL",
                    "https://generativelanguage.googleapis.com/v1beta/openai/",
                ),
                model=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
                api_key_env="GEMINI_API_KEY",
            )
        )
    if os.environ.get("OPENAI_API_KEY"):
        lista.append(
            Provedor(
                id="openai",
                label="OpenAI",
                base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                api_key_env="OPENAI_API_KEY",
            )
        )
    return lista
