"""Provedores de modelo disponíveis para o assistente (roteamento — requisito 8 do plano).

Cada provedor é um endpoint compatível com a API da OpenAI, então o mesmo OpenAICompatibleChat
serve a todos trocando base_url/model/chave:

- qwen: o modelo local servido por vLLM na GPU (padrão; "grátis" = sua GPU).
- gemini: Google Gemini pelo endpoint compatível com OpenAI (chave do Google AI Studio; tem
  camada gratuita). Ativa só se GEMINI_API_KEY estiver definido.
- openai: API da OpenAI (paga). Ativa só se OPENAI_API_KEY estiver definido.
- claude: API da Anthropic (paga). Não é compatível com OpenAI — usa o AnthropicChat (kind
  "anthropic"). Ativa só se ANTHROPIC_API_KEY estiver definido.

O campo `kind` diz qual cliente instanciar ("openai" para os compatíveis; "anthropic" p/ o Claude).
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
    kind: str = "openai"  # "openai" (compatível) ou "anthropic"

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
        base_gemini = os.environ.get(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        # Mesma chave/endpoint do Google AI Studio para as duas: "gratuito x pago" é só o
        # faturamento (billing) do projeto no Google, não config diferente aqui. O que se escolhe
        # é o modelo — um mais leve (econômico) e um mais forte.
        lista.append(
            Provedor(
                id="gemini",
                label="Google Gemini Flash (econômico)",
                base_url=base_gemini,
                model=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
                api_key_env="GEMINI_API_KEY",
            )
        )
        pro = os.environ.get("GEMINI_MODEL_PRO", "gemini-2.5-pro")
        if pro:  # GEMINI_MODEL_PRO="" desativa a entrada Pro
            lista.append(
                Provedor(
                    id="gemini-pro",
                    label="Google Gemini Pro (mais forte)",
                    base_url=base_gemini,
                    model=pro,
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
    if os.environ.get("ANTHROPIC_API_KEY"):
        lista.append(
            Provedor(
                id="claude",
                label="Anthropic Claude",
                base_url=os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
                model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
                api_key_env="ANTHROPIC_API_KEY",
                kind="anthropic",
            )
        )
    return lista
