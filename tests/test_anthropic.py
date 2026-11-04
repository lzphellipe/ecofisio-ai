"""Adaptador do Claude (Anthropic): tradução OpenAI<->Anthropic e parsing das respostas.

Usa httpx.MockTransport — sem rede, sem chave. Verifica o que o adaptador ENVIA (system no topo,
tool_use/tool_result nos blocos certos, schema das ferramentas) e o que ele LÊ de volta (texto,
tool_calls, uso de tokens).
"""

from __future__ import annotations

import json

import httpx

from ecofisio.agent.anthropic_chat import AnthropicChat, _para_anthropic, _tools_para_anthropic
from ecofisio.agent.providers import provedores

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_literatura",
            "description": "busca na literatura",
            "parameters": {"type": "object", "properties": {"consulta": {"type": "string"}}},
        },
    }
]


def _transport(handler):
    return httpx.MockTransport(handler)


def test_converte_system_tool_use_e_tool_result():
    messages = [
        {"role": "system", "content": "regras"},
        {"role": "user", "content": "pergunta"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "buscar_literatura", "arguments": '{"consulta": "x"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "trecho achado"},
    ]
    system, msgs = _para_anthropic(messages)
    assert system == "regras"
    # system não entra na lista de mensagens
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    # assistant carrega um bloco tool_use com input já desserializado
    bloco_uso = msgs[1]["content"][0]
    assert bloco_uso == {
        "type": "tool_use",
        "id": "c1",
        "name": "buscar_literatura",
        "input": {"consulta": "x"},
    }
    # o resultado da ferramenta vira tool_result num turno de user
    bloco_res = msgs[2]["content"][0]
    assert bloco_res["type"] == "tool_result" and bloco_res["tool_use_id"] == "c1"
    assert bloco_res["content"] == "trecho achado"


def test_tool_results_consecutivos_no_mesmo_turno():
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "a", "type": "function", "function": {"name": "t", "arguments": "{}"}},
                {"id": "b", "type": "function", "function": {"name": "t", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "a", "content": "r1"},
        {"role": "tool", "tool_call_id": "b", "content": "r2"},
    ]
    _, msgs = _para_anthropic(messages)
    # dois tool_result precisam ficar no MESMO turno de user (alternância user/assistant)
    assert [m["role"] for m in msgs] == ["assistant", "user"]
    assert [b["tool_use_id"] for b in msgs[1]["content"]] == ["a", "b"]


def test_schema_de_ferramentas():
    out = _tools_para_anthropic(TOOLS)
    assert out == [
        {
            "name": "buscar_literatura",
            "description": "busca na literatura",
            "input_schema": {"type": "object", "properties": {"consulta": {"type": "string"}}},
        }
    ]


def test_resposta_de_texto():
    def handler(request: httpx.Request) -> httpx.Response:
        enviado = json.loads(request.content)
        assert enviado["model"] == "claude-x"
        assert enviado["system"] == "regras"
        assert request.headers["x-api-key"] == "k"
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "resposta"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

    chat = AnthropicChat(
        "https://api.anthropic.com", "claude-x", api_key="k", transport=_transport(handler)
    )
    reply = chat.chat([{"role": "system", "content": "regras"}, {"role": "user", "content": "oi"}])
    assert reply.content == "resposta"
    assert not reply.tool_calls
    assert reply.finish_reason == "end_turn"
    assert reply.usage["total_tokens"] == 15
    chat.close()


def test_resposta_com_tool_use_vira_toolcall():
    def handler(request: httpx.Request) -> httpx.Response:
        enviado = json.loads(request.content)
        assert enviado["tools"][0]["name"] == "buscar_literatura"
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "vou buscar"},
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "buscar_literatura",
                        "input": {"consulta": "rubisco"},
                    },
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
        )

    chat = AnthropicChat(
        "https://api.anthropic.com", "claude-x", api_key="k", transport=_transport(handler)
    )
    reply = chat.chat([{"role": "user", "content": "q"}], tools=TOOLS)
    assert reply.content == "vou buscar"
    assert len(reply.tool_calls) == 1
    tc = reply.tool_calls[0]
    assert tc.id == "tu_1" and tc.name == "buscar_literatura"
    assert tc.arguments == {"consulta": "rubisco"}
    # raw_arguments é JSON válido para o rastro e para o round-trip no histórico
    assert json.loads(tc.raw_arguments) == {"consulta": "rubisco"}
    # as_message() reconstrói no formato OpenAI, e _para_anthropic reconverte sem perda
    msg = reply.as_message()
    _, msgs = _para_anthropic([msg])
    assert msgs[0]["content"][-1]["input"] == {"consulta": "rubisco"}
    chat.close()


def test_erro_http_vira_llmerror():
    import pytest

    from ecofisio.agent.llm import LLMError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="limite de uso")

    chat = AnthropicChat(
        "https://api.anthropic.com", "claude-x", api_key="k", transport=_transport(handler)
    )
    with pytest.raises(LLMError, match="400"):
        chat.chat([{"role": "user", "content": "q"}])
    chat.close()


def test_provedor_claude_ativa_com_a_chave(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
    provs = {p.id: p for p in provedores()}
    assert "claude" in provs
    claude = provs["claude"]
    assert claude.kind == "anthropic" and claude.model == "claude-haiku-5-5"
    assert claude.api_key == "k"
