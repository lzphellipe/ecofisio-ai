"""API HTTP: perguntar, histórico e login, com LLM roteirizado (sem rede, sem GPU)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ecofisio.agent import ChatReply, ResearchAgent, ToolCall
from ecofisio.api import create_app
from ecofisio.evidence import RetractionChecker, RetractionWatchIndex, SupportLabel
from ecofisio.evidence.verify import VerificationResult
from ecofisio.literature import parse_jats
from ecofisio.rag import LiteratureIndex

FIXTURE = Path(__file__).parent / "fixtures" / "jats_cc_by.xml"
DOI = "10.5555/test.drought.001"


class Scripted:
    name = "roteiro"

    def __init__(self, replies):
        self.replies = list(replies)

    def chat(self, messages, tools=None):
        return self.replies.pop(0)

    def close(self):
        pass


class FixedVerifier:
    name = "nli-fixo"

    def __init__(self, label):
        self.label = label

    def verify(self, claim, passage):
        return VerificationResult(self.label, 0.1, 0.9, self.name)


def search(q="stomatal conductance drought"):
    args = {"consulta": q}
    return ChatReply("", [ToolCall("c1", "buscar_literatura", args, json.dumps(args))])


def final(claims, gaps=()):
    return ChatReply(json.dumps({"resumo": "r", "afirmacoes": claims, "lacunas": list(gaps)}))


def claim(text="A seca reduz a condutância.", cits=("T1",)):
    return {"texto": text, "forca": "resultado_isolado", "status": "medido", "citacoes": list(cits)}


def checker(tmp_path):
    p = tmp_path / "rw.csv"
    p.write_text("Record ID,OriginalPaperDOI,RetractionDOI,RetractionNature\n", "utf-8")
    return RetractionChecker(index=RetractionWatchIndex.from_csv(p))


def make_agent(tmp_path, replies):
    idx = LiteratureIndex()
    idx.add_article(parse_jats(FIXTURE.read_bytes()))
    verifier = FixedVerifier(SupportLabel.SUSTENTA)
    return ResearchAgent(Scripted(replies), idx, checker(tmp_path), verifier)


def test_perguntar_delivers_and_records_history(tmp_path):
    agent = make_agent(tmp_path, [search(), final([claim()])])
    app = create_app(agent, runs_dir=tmp_path / "runs", users={})
    client = TestClient(app)

    r = client.post("/perguntar", json={"pergunta": "O que a seca faz com a condutância?"})
    assert r.status_code == 200
    data = r.json()
    assert data["entregues"] and data["entregues"][0]["citacoes"][0]["doi"] == DOI
    assert data["bloqueadas"] == [] and "id" in data

    hist = client.get("/historico").json()
    assert len(hist) == 1 and hist[0]["id"] == data["id"] and hist[0]["entregues"] == 1

    item = client.get(f"/historico/{data['id']}").json()
    assert item["pergunta"] == "O que a seca faz com a condutância?"


def test_perguntar_blocks_invented_citation(tmp_path):
    agent = make_agent(tmp_path, [search(), final([claim(cits=["T99"])])])
    app = create_app(agent, runs_dir=tmp_path / "runs", users={})
    data = TestClient(app).post("/perguntar", json={"pergunta": "q"}).json()
    assert data["entregues"] == [] and data["bloqueadas"]  # T99 não existe → bloqueada


def test_health_and_validation(tmp_path):
    agent = make_agent(tmp_path, [])
    client = TestClient(create_app(agent, runs_dir=tmp_path / "runs", users={}))
    s = client.get("/saude").json()
    assert s["status"] == "ok" and s["modelo"] == "roteiro" and s["trechos"] > 0
    assert client.post("/perguntar", json={"pergunta": ""}).status_code == 422  # min_length


def test_history_item_rejects_path_traversal(tmp_path):
    agent = make_agent(tmp_path, [])
    client = TestClient(create_app(agent, runs_dir=tmp_path / "runs", users={}))
    assert client.get("/historico/..%2F..%2Fetc%2Fpasswd").status_code in (400, 404)
    assert client.get("/historico/nao-existe").status_code == 404


def test_login_required_when_users_set(tmp_path):
    agent = make_agent(tmp_path, [search(), final([claim()])])
    app = create_app(agent, runs_dir=tmp_path / "runs", users={"luiz": "s3nha"})
    client = TestClient(app)
    assert client.get("/saude").status_code == 401
    assert client.get("/saude", auth=("luiz", "errada")).status_code == 401
    assert client.get("/saude", auth=("luiz", "s3nha")).status_code == 200


def test_cors_origin_allowed(tmp_path):
    agent = make_agent(tmp_path, [])
    app = create_app(
        agent, runs_dir=tmp_path / "runs", users={}, cors_origins=["http://localhost:5173"]
    )
    client = TestClient(app)
    r = client.get("/saude", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a:1,b:2", {"a": "1", "b": "2"}),
        ("", {}),
        ("semcolon", {}),
        (" u : p ", {"u": " p "}),  # usuário trim, senha preservada
    ],
)
def test_parse_users(raw, expected):
    from ecofisio.api.app import _parse_users

    assert _parse_users(raw) == expected
