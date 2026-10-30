"""Pipeline de dataset de SFT: destilação, portão de qualidade, recusas, split e manifesto.

Usa um LLM roteirizado (sem rede, sem GPU): o foco é a mecânica do portão e do empacotamento.
"""

import json
from pathlib import Path

import pytest

from ecofisio.agent import ChatReply, ResearchAgent, ToolCall
from ecofisio.dataset import (
    REFUSAL_EXAMPLES,
    SFTExample,
    example_from_answer,
    manifest,
    split_train_val,
)
from ecofisio.dataset.schema import TIPOS, dumps_jsonl
from ecofisio.dataset.seeds import SeedQuestion
from ecofisio.evidence import RetractionChecker, RetractionWatchIndex, SupportLabel
from ecofisio.evidence.verify import VerificationResult
from ecofisio.literature import parse_jats
from ecofisio.rag import LiteratureIndex

FIXTURE = Path(__file__).parent / "fixtures" / "jats_cc_by.xml"
DOI = "10.5555/test.drought.001"
FACTUAL = SeedQuestion("pergunta factual?", "factual", "bioquimica", "graduacao")
FORA = SeedQuestion("fora do escopo?", "sem_resposta", "ecologia", "pos")


class Scripted:
    name = "roteiro"

    def __init__(self, replies):
        self.replies = list(replies)

    def chat(self, messages, tools=None):
        return self.replies.pop(0)

    def close(self):
        pass


def search(q="stomatal conductance drought"):
    args = {"consulta": q}
    return ChatReply("", [ToolCall("c1", "buscar_literatura", args, json.dumps(args))])


def final(claims, gaps=()):
    return ChatReply(json.dumps({"resumo": "r", "afirmacoes": claims, "lacunas": list(gaps)}))


def claim(text="ok", forca="resultado_isolado", status="medido", cits=("T1",)):
    return {"texto": text, "forca": forca, "status": status, "citacoes": list(cits)}


class FixedVerifier:
    name = "nli-fixo"

    def __init__(self, label):
        self.label = label

    def verify(self, claim, passage):
        return VerificationResult(self.label, 0.1, 0.9, self.name)


@pytest.fixture
def index():
    idx = LiteratureIndex()
    idx.add_article(parse_jats(FIXTURE.read_bytes()))
    return idx


def checker(tmp_path):
    p = tmp_path / "rw.csv"
    p.write_text("Record ID,OriginalPaperDOI,RetractionDOI,RetractionNature\n", "utf-8")
    return RetractionChecker(index=RetractionWatchIndex.from_csv(p))


def run(tmp_path, index, replies, verifier=None, require_semantic=True):
    agent = ResearchAgent(
        Scripted(replies), index, checker(tmp_path), verifier, require_semantic=require_semantic
    )
    return agent.ask("q")


# ---- portão de qualidade ----------------------------------------------------------------------
def test_good_factual_becomes_example(tmp_path, index):
    ans = run(tmp_path, index, [search(), final([claim()])], FixedVerifier(SupportLabel.SUSTENTA))
    ex = example_from_answer(ans, FACTUAL)
    assert ex is not None
    assert ex.tipo == "factual" and ex.area == "bioquimica" and ex.origem == "destilado"
    assert ex.messages[0]["role"] == "system" and ex.messages[-1]["role"] == "assistant"
    assert DOI in ex.dois  # o DOI citado foi registrado para auditoria de licença


def test_blocked_claim_discards_whole_example(tmp_path, index):
    # afirmação cita trecho inexistente → bloqueada → exemplo inteiro descartado
    ans = run(tmp_path, index, [search(), final([claim(cits=["T99"])])])
    assert ans.blocked and example_from_answer(ans, FACTUAL) is None


def test_factual_without_delivery_is_discarded(tmp_path, index):
    ans = run(tmp_path, index, [search(), final([], gaps=["nada"])])
    assert example_from_answer(ans, FACTUAL) is None


def test_repair_discards_example(tmp_path, index):
    # primeira resposta final inválida → reparo; mesmo recuperando, não vira exemplo
    bad = ChatReply("isso não é json")
    ans = run(
        tmp_path, index, [search(), bad, final([claim()])], FixedVerifier(SupportLabel.SUSTENTA)
    )
    assert ans.repairs == 1 and example_from_answer(ans, FACTUAL) is None


def test_abstention_is_kept_and_strong_answer_is_not(tmp_path, index):
    abst = run(tmp_path, index, [search(), final([], gaps=["fora do corpus"])])
    assert example_from_answer(abst, FORA) is not None
    strong = run(
        tmp_path, index, [search(), final([claim()])], FixedVerifier(SupportLabel.SUSTENTA)
    )
    assert example_from_answer(strong, FORA) is None  # entregou afirmação forte: não é abstenção


# ---- recusas escritas à mão -------------------------------------------------------------------
def test_refusal_examples_are_clean(tmp_path):
    assert REFUSAL_EXAMPLES
    for ex in REFUSAL_EXAMPLES:
        assert ex.tipo == "seguranca" and ex.origem == "manual"
        assert not any(m.get("tool_calls") for m in ex.messages)  # recusa sem buscar
        final_msg = json.loads(ex.messages[-1]["content"])
        assert final_msg["afirmacoes"] == [] and final_msg["lacunas"]


# ---- split e manifesto ------------------------------------------------------------------------
def ex(tipo="factual", area="x", nivel="pos", q="p", dois=()):
    return SFTExample(
        messages=[
            {"role": "system", "content": "s"},
            {"role": "user", "content": q},
            {"role": "assistant", "content": "{}"},
        ],
        tipo=tipo,
        area=area,
        nivel=nivel,
        dois=list(dois),
    )


def test_split_is_deterministic_and_stable():
    items = [ex(q=f"pergunta {i}") for i in range(40)]
    a1, b1 = split_train_val(items, 25)
    a2, b2 = split_train_val(items, 25)
    assert [e.key for e in a1] == [e.key for e in a2]  # determinístico
    assert [e.key for e in b1] == [e.key for e in b2]
    assert len(a1) + len(b1) == 40 and b1  # há validação
    assert set(e.key for e in a1).isdisjoint(e.key for e in b1)  # sem sobreposição
    with pytest.raises(ValueError):
        split_train_val(items, 150)


def test_manifest_counts_by_facets():
    items = [
        ex(tipo="factual", area="bioquimica", dois=[DOI]),
        ex(tipo="factual", area="ecologia"),
        ex(tipo="seguranca", area=""),
    ]
    m = manifest(items)
    assert m["n_exemplos"] == 3
    assert m["por_tipo"] == {"factual": 2, "seguranca": 1}
    assert m["por_area"]["bioquimica"] == 1 and m["por_area"]["(vazio)"] == 1
    assert m["dois_citados"] == [DOI]


def test_schema_rejects_malformed_and_jsonl_roundtrips():
    with pytest.raises(ValueError):
        SFTExample(messages=[{"role": "user", "content": "x"}], tipo="factual")
    with pytest.raises(ValueError):
        ex(tipo="invalido")
    assert TIPOS == {"factual", "sem_resposta", "seguranca"}
    line = dumps_jsonl([ex(q="só uma")]).strip()
    obj = json.loads(line)
    assert obj["meta"]["tipo"] == "factual" and obj["messages"][1]["content"] == "só uma"


# ---- CLI de ponta a ponta ---------------------------------------------------------------------
def test_cli_writes_dataset(tmp_path, monkeypatch, index, capsys):
    import ecofisio.dataset.cli as cli

    def fake_build_agent(args, ap):
        agent = ResearchAgent(
            Scripted([search(), final([claim()])]),
            index,
            checker(tmp_path),
            FixedVerifier(SupportLabel.SUSTENTA),
        )
        return agent, agent.model, index

    monkeypatch.setattr(cli, "build_agent", fake_build_agent)
    out = tmp_path / "sft"
    rc = cli.main(["--crossref-email", "x@example.org", "--out", str(out), "--limite", "1"])
    assert rc == 0
    man = json.loads((out / "manifest.json").read_text())
    # 1 factual destilado + 3 recusas manuais
    assert man["por_tipo"]["factual"] == 1 and man["por_tipo"]["seguranca"] == 3
    assert man["n_treino"] + man["n_validacao"] == man["n_exemplos"] == 4
    assert len((out / "train.jsonl").read_text().splitlines()) == man["n_treino"]
    assert "sha256_treino" in man and man["modelo_destilador"] == "roteiro"
