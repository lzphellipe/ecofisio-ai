"""Adaptador para a API da Anthropic (Claude), que não é compatível com OpenAI.

Implementa o mesmo protocolo ChatModel (chat(messages, tools) -> ChatReply) do OpenAICompatibleChat,
traduzindo o histórico no formato OpenAI (system/user/assistant/tool, com tool_calls) para o formato
Messages da Anthropic (system no topo; tool_use em blocos do assistant; tool_result em blocos do
user) e de volta. Assim o ResearchAgent funciona igual, trocando só o provedor no seletor.

Precisa de ANTHROPIC_API_KEY. A primeira execução real deve ser validada (uso de ferramenta com
Claude segue o formato documentado, mas não dá para exercitar sem a chave).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from ecofisio.agent.llm import ChatReply, LLMError, ToolCall


def _para_anthropic(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Converte o histórico OpenAI em (system, messages) do formato Anthropic."""
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            if m.get("content"):
                system_parts.append(str(m["content"]))
        elif role == "user":
            out.append({"role": "user", "content": m.get("content", "")})
        elif role == "assistant":
            blocks: list[dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                try:
                    inp = json.loads(args) if isinstance(args, str) else (args or {})
                except (ValueError, TypeError):
                    inp = {}
                blocks.append(
                    {"type": "tool_use", "id": tc.get("id"), "name": fn.get("name"), "input": inp}
                )
            out.append({"role": "assistant", "content": blocks or ""})
        elif role == "tool":
            bloco = {
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id"),
                "content": m.get("content", ""),
            }
            # resultados de ferramenta consecutivos entram no mesmo turno de user
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(bloco)
            else:
                out.append({"role": "user", "content": [bloco]})
    return "\n\n".join(system_parts), out


def _tools_para_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tools:
        fn = t.get("function") or {}
        out.append(
            {
                "name": fn.get("name"),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters") or {"type": "object"},
            }
        )
    return out


class AnthropicChat:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        version: str = "2023-06-01",
        max_tokens: int = 2048,
        timeout: float = 180.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.name = model
        self._max_tokens = max_tokens
        headers = {
            "anthropic-version": version,
            "content-type": "application/json",
        }
        if api_key:
            headers["x-api-key"] = api_key
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, headers=headers, transport=transport
        )

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> ChatReply:
        system, msgs = _para_anthropic(messages)
        payload: dict[str, Any] = {
            "model": self.name,
            "max_tokens": self._max_tokens,
            "messages": msgs,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = _tools_para_anthropic(tools)
        try:
            resp = self._http.post("/v1/messages", json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"sem resposta do Claude: {exc}") from exc
        if resp.status_code != 200:
            raise LLMError(f"HTTP {resp.status_code} do Claude: {resp.text[:500]}")
        try:
            data = resp.json()
            blocks = data.get("content") or []
        except (ValueError, KeyError) as exc:
            raise LLMError(f"resposta fora do formato Anthropic: {resp.text[:500]}") from exc

        texto = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        calls = []
        for i, b in enumerate(b for b in blocks if b.get("type") == "tool_use"):
            inp = b.get("input") or {}
            calls.append(
                ToolCall(
                    id=b.get("id") or f"call_{i}",
                    name=b.get("name", ""),
                    arguments=inp if isinstance(inp, dict) else {},
                    raw_arguments=json.dumps(inp, ensure_ascii=False),
                )
            )
        u = data.get("usage") or {}
        entrada, saida = u.get("input_tokens"), u.get("output_tokens")
        usage: dict[str, Any] = {"prompt_tokens": entrada, "completion_tokens": saida}
        if isinstance(entrada, int) and isinstance(saida, int):
            usage["total_tokens"] = entrada + saida
        return ChatReply(
            content=texto, tool_calls=calls, finish_reason=data.get("stop_reason"), usage=usage
        )

    def close(self) -> None:
        self._http.close()
