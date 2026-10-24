"""Cliente de chat para qualquer servidor compatível com a API da OpenAI.

Funciona com vLLM (`vllm serve ...`), Ollama, LM Studio e LLMs de ponta que exponham a mesma API.
Isso deixa o roteamento entre modelos (requisito 8 do plano) como troca de `base_url`/`model`.

Escrito sobre httpx, sem o SDK da OpenAI: o projeto só precisa de `POST /chat/completions`.

Qwen 3 no vLLM (documentação do Qwen, qwen.readthedocs.io/en/v3.0/deployment/vllm.html):
- chamada de ferramentas: `--enable-auto-tool-choice --tool-call-parser hermes`
- modo de raciocínio desligado por requisição: `chat_template_kwargs={"enable_thinking": False}`
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str  # texto original, guardado para o rastro mesmo se o JSON vier inválido


@dataclass(slots=True)
class ChatReply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning: str | None = (
        None  # `reasoning_content` do vLLM, quando o parser de raciocínio está ativo
    )
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)

    def as_message(self) -> dict[str, Any]:
        """Mensagem do assistente para reenviar no histórico (sem o raciocínio)."""
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.raw_arguments},
                }
                for tc in self.tool_calls
            ]
        return msg


class ChatModel(Protocol):
    name: str

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> ChatReply: ...


class LLMError(RuntimeError):
    """O servidor respondeu com erro ou num formato inesperado."""


def _parse_arguments(raw: str | dict[str, Any] | None) -> tuple[dict[str, Any], str]:
    if isinstance(raw, dict):
        return raw, json.dumps(raw, ensure_ascii=False)
    text = raw or "{}"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"__invalid_json__": text}, text
    return (parsed if isinstance(parsed, dict) else {"__invalid_json__": text}), text


class OpenAICompatibleChat:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout: float = 180.0,
        extra_body: dict[str, Any] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.name = model
        self._payload_base: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **(extra_body or {}),
        }
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            timeout=timeout,
            headers=headers,
            transport=transport,
        )

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> ChatReply:
        payload = {**self._payload_base, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            resp = self._http.post("chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"sem resposta do servidor de LLM: {exc}") from exc
        if resp.status_code != 200:
            raise LLMError(f"HTTP {resp.status_code} do servidor de LLM: {resp.text[:500]}")
        try:
            data = resp.json()
            choice = data["choices"][0]
            msg = choice["message"]
        except (ValueError, KeyError, IndexError) as exc:
            raise LLMError(f"resposta fora do formato OpenAI: {resp.text[:500]}") from exc

        calls = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            args, raw = _parse_arguments(fn.get("arguments"))
            calls.append(
                ToolCall(
                    id=tc.get("id") or f"call_{i}",
                    name=fn.get("name", ""),
                    arguments=args,
                    raw_arguments=raw,
                )
            )
        return ChatReply(
            content=msg.get("content") or "",
            tool_calls=calls,
            reasoning=msg.get("reasoning_content"),
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage") or {},
        )

    def close(self) -> None:
        self._http.close()
