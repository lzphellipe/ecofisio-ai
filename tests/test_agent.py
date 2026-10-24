"""Agente de pesquisa com LLM simulado (roteiro fixo de respostas) e servidor OpenAI simulado."""

import json
from pathlib import Path

import httpx
import pytest

from ecofisio.agent import (
    AgentError,
    ChatReply,
    LLMError,
    OpenAICompatibleChat,
    ResearchAgent,
    ToolCall,
    parse_final_json,
    render_text,
)
from ecofisio.evidence import RetractionChecker, RetractionWatchIndex, SupportLabel
from ecofisio.evidence.verify import VerificationResult
from ecofisio.literature import Article, License, Paragraph, parse_jats
from ecofisio.rag import LiteratureIndex

FIXTURE = Path(__file__).parent / "fixtures" / "jats_cc_by.xml"


class ScriptedChat:
    """Devolve as respostas na ordem; guarda o que recebeu."""

    name = "roteiro-teste"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        return self.replies.pop(0)


class AlwaysSupports:
    name = "nli-falso"

    def verify(self, claim, passage):
        return VerificationResult(SupportLabel.SUSTENTA, 0.95, 0.01, self.name)


def search_call(query, cid="c1"):
    args = json.dumps({"consulta": query, "k": 3})
    return ChatReply("", [ToolCall(cid, "buscar_literatura", json.loads(args), args)])


def final(obj):
    return ChatReply(json.dumps(obj, ensure_ascii=False))


@pytest.fixture
def index():
    idx = LiteratureIndex()
    idx.add_article(parse_jats(FIXTURE.read_bytes()))
    idx.add_article(
        Article(
            pmcid=None,
            doi="10.5555/editorial",
            title="Editorial on drought",
            year=2024,
            journal=None,
            license=License.CC_BY,
            license_source="t",
            article_type="editorial",
            paragraphs=[Paragraph("Body", "Drought reduces stomatal conductance in many crops.")],
        )
    )
    return idx


@pytest.fixture
def checker(tmp_path):
    p = tmp_path / "rw.csv"
    p.write_text("Record ID,OriginalPaperDOI,RetractionDOI,RetractionNature\n", encoding="utf-8")
    return RetractionChecker(index=RetractionWatchIndex.from_csv(p))


def agent(model, index, checker, **kw):
    return ResearchAgent(model, index, checker, kw.pop("verifier", AlwaysSupports()), **kw)


def test_end_to_end_citations_come_from_real_passages(index, checker):
    model = ScriptedChat(
        [
            search_call("stomatal conductance drought"),
            final(
                {
                    "resumo": "A seca reduz a condutância estomática.",
                    "afirmacoes": [
                        {
                            "texto": "Sob seca severa, gs caiu abaixo de 0,05.",
                            "forca": "resultado isolado",
                            "status": "Medido",
                            "citacoes": ["t1"],
                        },
                        {
                            "texto": "Citação inventada.",
                            "forca": "resultado_isolado",
                            "status": "medido",
                            "citacoes": ["T9"],
                        },
                        {
                            "texto": "Consenso com um artigo só.",
                            "forca": "consenso",
                            "status": "medido",
                            "citacoes": ["T1"],
                        },
                        {
                            "texto": "Talvez dependa da espécie.",
                            "forca": "especulação",
                            "status": "inferido",
                            "citacoes": [],
                        },
                    ],
                    "lacunas": ["Não há dados de café adulto."],
                }
            ),
        ]
    )
    ans = agent(model, index, checker).ask("Qual o efeito da seca na condutância estomática?")

    assert [r.claim.text for r in ans.delivered] == [
        "Sob seca severa, gs caiu abaixo de 0,05.",
        "Talvez dependa da espécie.",
    ]
    cit = ans.delivered[0].claim.citations[0]
    real = next(p for p in index.passages if p.text == cit.passage)  # trecho é o texto real
    assert cit.doi == real.doi and cit.page == real.section
    blocked = {b.text: " ".join(b.reasons) for b in ans.blocked}
    assert "inexistente" in blocked["Citação inventada."]
    assert "consenso" in blocked["Consenso com um artigo só."]
    assert ans.gaps == ["Não há dados de café adulto."]
    assert ans.searches == ["stomatal conductance drought"]
    # a ferramenta foi oferecida e o resultado voltou ao modelo como mensagem 'tool'
    assert model.calls[0]["tools"][0]["function"]["name"] == "buscar_literatura"
    tool_msg = model.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1"
    assert json.loads(tool_msg["content"])["resultados"][0]["id"] == "T1"


def test_without_verifier_cited_claims_are_blocked(index, checker):
    model = ScriptedChat(
        [
            search_call("drought"),
            final(
                {
                    "resumo": "x",
                    "afirmacoes": [
                        {
                            "texto": "A caiu 40%.",
                            "forca": "resultado_isolado",
                            "status": "medido",
                            "citacoes": ["T1"],
                        }
                    ],
                }
            ),
        ]
    )
    ans = agent(model, index, checker, verifier=None).ask("q")
    assert not ans.delivered
    assert "sustentação semântica não verificada" in ans.blocked[0].reasons


def test_measured_claim_citing_only_editorial_gets_warning(index, checker):
    model = ScriptedChat([search_call("editorial drought stomatal crops"), None])
    ag = agent(model, index, checker)
    model.replies[1] = None  # preenchido depois de saber o ID do editorial

    def patched_chat(messages, tools=None):
        if model.replies and model.replies[0] is None:
            res = json.loads(messages[-1]["content"])["resultados"]
            ed = next(r["id"] for r in res if r["article_type"] == "editorial")
            model.replies[0] = final(
                {
                    "resumo": "x",
                    "afirmacoes": [
                        {
                            "texto": "A seca reduz gs.",
                            "forca": "resultado_isolado",
                            "status": "medido",
                            "citacoes": [ed],
                        }
                    ],
                }
            )
        return ScriptedChat.chat(model, messages, tools)

    model.chat = patched_chat
    ans = ag.ask("q")
    assert ans.delivered and any("não primárias" in w for w in ans.delivered[0].warnings)


def test_invalid_json_gets_one_repair(index, checker):
    model = ScriptedChat(
        [
            ChatReply("Aqui está a resposta, sem JSON."),
            ChatReply('<think>pensando</think>```json\n{"resumo": "ok", "afirmacoes": []}\n```'),
        ]
    )
    ans = agent(model, index, checker).ask("q")
    assert ans.summary == "ok"
    assert "não é um JSON válido" in model.calls[1]["messages"][-1]["content"]


def test_gives_up_after_repairs(index, checker):
    model = ScriptedChat([ChatReply("nada"), ChatReply("ainda nada")])
    with pytest.raises(AgentError):
        agent(model, index, checker).ask("q")


def test_step_limit_forces_final_answer_without_tools(index, checker):
    model = ScriptedChat(
        [search_call("a", "c1"), search_call("b", "c2"), final({"resumo": "fim", "afirmacoes": []})]
    )
    ans = agent(model, index, checker, max_steps=2).ask("q")
    assert ans.summary == "fim"
    assert model.calls[-1]["tools"] is None
    assert "Limite de buscas" in model.calls[-1]["messages"][-1]["content"]


def test_parse_final_json_variants():
    assert parse_final_json('texto {"a": 1} fim') == {"a": 1}
    with pytest.raises(ValueError):
        parse_final_json("sem json")


def test_render_text_shows_delivered_and_blocked(index, checker):
    model = ScriptedChat(
        [
            search_call("drought"),
            final(
                {
                    "resumo": "R",
                    "afirmacoes": [
                        {
                            "texto": "Ok.",
                            "forca": "resultado_isolado",
                            "status": "medido",
                            "citacoes": ["T1"],
                        },
                        {"texto": "Ruim.", "forca": "x", "status": "medido", "citacoes": ["T1"]},
                    ],
                }
            ),
        ]
    )
    txt = render_text(agent(model, index, checker).ask("q"))
    assert "Afirmações verificadas (1)" in txt and "Afirmações bloqueadas (1)" in txt
    assert "doi:10.5555/" in txt


# ---- cliente OpenAI-compatível ----------------------------------------------------------------
def test_openai_client_payload_and_tool_call_parsing():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "reasoning_content": "raciocínio",
                            "tool_calls": [
                                {
                                    "id": "x1",
                                    "type": "function",
                                    "function": {
                                        "name": "buscar_literatura",
                                        "arguments": '{"consulta": "vcmax"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"total_tokens": 10},
            },
        )

    chat = OpenAICompatibleChat(
        "http://gpu:8000/v1",
        "Qwen/Qwen3-8B",
        api_key="segredo",
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        transport=httpx.MockTransport(handler),
    )
    r = chat.chat([{"role": "user", "content": "oi"}], tools=[{"type": "function"}])
    assert seen["url"] == "http://gpu:8000/v1/chat/completions"
    assert seen["auth"] == "Bearer segredo"
    assert seen["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen["body"]["tool_choice"] == "auto" and seen["body"]["model"] == "Qwen/Qwen3-8B"
    assert r.tool_calls[0].arguments == {"consulta": "vcmax"} and r.reasoning == "raciocínio"
    msg = r.as_message()
    assert msg["tool_calls"][0]["function"]["arguments"] == '{"consulta": "vcmax"}'
    assert "reasoning" not in json.dumps(msg)


def test_openai_client_invalid_arguments_and_errors():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "x",
                                    "function": {
                                        "name": "buscar_literatura",
                                        "arguments": "{quebrado",
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    r = OpenAICompatibleChat("http://h/v1", "m", transport=httpx.MockTransport(handler)).chat([])
    assert "__invalid_json__" in r.tool_calls[0].arguments

    bad = OpenAICompatibleChat(
        "http://h/v1", "m", transport=httpx.MockTransport(lambda r: httpx.Response(500, text="x"))
    )
    with pytest.raises(LLMError):
        bad.chat([])


def test_cli_end_to_end_with_fake_server(tmp_path, monkeypatch, capsys, index):
    import ecofisio.agent.cli as cli

    index.save(tmp_path / "idx")
    rw = tmp_path / "rw.csv"
    rw.write_text("Record ID,OriginalPaperDOI,RetractionDOI,RetractionNature\n", encoding="utf-8")
    script = ScriptedChat(
        [
            search_call("stomatal conductance drought"),
            final(
                {
                    "resumo": "Resumo.",
                    "afirmacoes": [
                        {
                            "texto": "A caiu.",
                            "forca": "resultado_isolado",
                            "status": "medido",
                            "citacoes": ["T1"],
                        }
                    ],
                }
            ),
        ]
    )
    script.close = lambda: None
    seen = {}

    def fake_chat(base_url, model, *, api_key=None, extra_body=None, **kw):
        seen.update(base_url=base_url, model=model, api_key=api_key, extra_body=extra_body)
        return script

    monkeypatch.setattr(cli, "OpenAICompatibleChat", fake_chat)
    monkeypatch.setenv("ECOFISIO_LLM_KEY", "k123")
    code = cli.main(
        [
            "Efeito da seca?",
            "--index",
            str(tmp_path / "idx"),
            "--rw-csv",
            str(rw),
            "--sem-verificacao-semantica",
            "--rastro",
            str(tmp_path / "runs"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0 and "Afirmações verificadas (1)" in out
    assert seen["api_key"] == "k123"
    assert seen["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    trace = json.loads(next((tmp_path / "runs").glob("*.json")).read_text())
    assert trace["entregues"][0]["avisos"]  # sem verificação semântica: aviso registrado
    assert trace["buscas"] == ["stomatal conductance drought"]


def test_cli_requires_retraction_source(tmp_path, index):
    import ecofisio.agent.cli as cli

    index.save(tmp_path / "idx")
    with pytest.raises(SystemExit):
        cli.main(["q", "--index", str(tmp_path / "idx")])
