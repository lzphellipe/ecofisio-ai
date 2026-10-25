"""Avaliador: benchmark, métricas (com motivos gerados pelo código real), bootstrap e comparação."""

import json
from pathlib import Path

import pytest

from ecofisio.agent import AgentError, ChatReply, ResearchAgent, ToolCall
from ecofisio.eval import (
    METRICS,
    bootstrap_ci,
    classify_reason,
    compare,
    load_benchmark,
    run_benchmark,
    score,
    summarize,
)
from ecofisio.eval.benchmark import BenchmarkItem
from ecofisio.evidence import RetractionChecker, RetractionWatchIndex, SupportLabel
from ecofisio.evidence.verify import VerificationResult
from ecofisio.literature import parse_jats
from ecofisio.rag import LiteratureIndex

ROOT = Path(__file__).parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "jats_cc_by.xml"
DOI = "10.5555/test.drought.001"


# ---- utilitários ------------------------------------------------------------------------------
class Scripted:
    name = "roteiro"

    def __init__(self, replies):
        self.replies = list(replies)

    def chat(self, messages, tools=None):
        return self.replies.pop(0)


def search(q="stomatal conductance drought"):
    args = {"consulta": q}
    return ChatReply("", [ToolCall("c1", "buscar_literatura", args, json.dumps(args))])


def final(claims, gaps=()):
    return ChatReply(json.dumps({"resumo": "r", "afirmacoes": claims, "lacunas": list(gaps)}))


def claim(text, forca="resultado_isolado", status="medido", cits=("T1",)):
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


def checker(tmp_path, retracted=()):
    p = tmp_path / "rw.csv"
    rows = "".join(f"{i},{d},10.5555/aviso.{i},Retraction\n" for i, d in enumerate(retracted))
    p.write_text("Record ID,OriginalPaperDOI,RetractionDOI,RetractionNature\n" + rows, "utf-8")
    return RetractionChecker(index=RetractionWatchIndex.from_csv(p))


# ---- benchmark --------------------------------------------------------------------------------
def test_seed_benchmark_loads():
    b = load_benchmark(ROOT / "benchmarks" / "semente.jsonl")
    assert len(b) == 13 and len(b.sha256) == 64
    assert {i.tipo for i in b.items} == {"factual", "sem_resposta", "armadilha"}
    assert all(i.avaliacao == "manual" for i in b.items if i.tipo == "armadilha")


@pytest.mark.parametrize(
    "line",
    [
        '{"id": "x", "pergunta": "p", "tipo": "outro"}',
        '{"id": "", "pergunta": "p", "tipo": "factual"}',
        '{"id": "x", "pergunta": "p", "tipo": "sem_resposta", "dois_esperados": ["10.5555/a"]}',
        '{"id": "x", "pergunta": "p", "tipo": "factual"}\n'
        '{"id": "x", "pergunta": "q", "tipo": "factual"}',
        "{quebrado",
    ],
    ids=["tipo", "sem-id", "doi-fora-factual", "id-repetido", "json"],
)
def test_benchmark_validation(tmp_path, line):
    f = tmp_path / "b.jsonl"
    f.write_text(line + "\n", "utf-8")
    with pytest.raises(ValueError):
        load_benchmark(f)


# ---- motivos de bloqueio vindos do código real ------------------------------------------------
def test_every_real_block_reason_is_classified(tmp_path, index):
    script = [
        search(),
        final(
            [
                claim("inventada", cits=("T9",)),
                claim("força ruim", forca="talvez"),
                claim("status ruim", status="achismo"),
                claim("consenso de um", forca="consenso"),
                claim("sem citação", cits=()),
                claim("ok"),
            ]
        ),
    ]
    ans = ResearchAgent(Scripted(script), index, checker(tmp_path), None).ask("q")
    reasons = [r for b in ans.blocked for r in b.reasons]
    cats = {classify_reason(r) for r in reasons}
    assert cats == {
        "citacao_inventada",
        "forca_invalida",
        "status_invalido",
        "consenso_insuficiente",
        "sem_citacao",
        "semantica_nao_verificada",
    }

    for label, expected in [
        (SupportLabel.NAO_SUSTENTA, "trecho_nao_sustenta"),
        (SupportLabel.CONTRADIZ, "trecho_contradiz"),
    ]:
        ans = ResearchAgent(
            Scripted([search(), final([claim("x")])]),
            index,
            checker(tmp_path),
            FixedVerifier(label),
        ).ask("q")
        assert classify_reason(ans.blocked[0].reasons[0]) == expected

    ans = ResearchAgent(
        Scripted([search(), final([claim("x")])]),
        index,
        checker(tmp_path, [DOI]),
        FixedVerifier(SupportLabel.SUSTENTA),
    ).ask("q")
    assert classify_reason(ans.blocked[0].reasons[0]) == "retratado"
    assert classify_reason("algo novo") == "outro"


# ---- métricas por pergunta --------------------------------------------------------------------
def test_score_recall_and_out_of_index(tmp_path, index):
    ans = ResearchAgent(
        Scripted([search(), final([claim("ok")])]),
        index,
        checker(tmp_path),
        FixedVerifier(SupportLabel.SUSTENTA),
    ).ask("q")
    item = BenchmarkItem("f1", "q", "factual", (DOI, "10.5555/nao.indexado"))
    r = score(item, ans, latency_s=1.5, indexed_dois={DOI})
    assert r.recall_dois == 1.0  # o DOI fora do índice não entra no denominador
    assert r.dois_esperados_fora_do_indice == ["10.5555/nao.indexado"]
    assert r.entregues == r.entregues_fortes == 1 and r.buscas == 1 and r.passos == 2


def test_abstention_on_out_of_scope(tmp_path, index):
    item = BenchmarkItem("s1", "q", "sem_resposta")
    ok = ResearchAgent(
        Scripted([search(), final([], gaps=["fora do corpus"])]), index, checker(tmp_path)
    ).ask("q")
    assert score(item, ok, latency_s=1, indexed_dois=set()).absteve_corretamente is True
    bad = ResearchAgent(
        Scripted([search(), final([claim("afirma")])]),
        index,
        checker(tmp_path),
        FixedVerifier(SupportLabel.SUSTENTA),
    ).ask("q")
    assert score(item, bad, latency_s=1, indexed_dois=set()).absteve_corretamente is False
    err = score(item, None, latency_s=1, indexed_dois=set(), error="x")
    assert err.absteve_corretamente is None and not err.ok


def test_safety_benchmark_loads_and_validates(tmp_path):
    b = load_benchmark(ROOT / "benchmarks" / "seguranca.jsonl")
    assert {i.tipo for i in b.items} == {"seguranca"}
    assert all(i.avaliacao == "manual" for i in b.items)  # uso duplo é revisão humana
    assert [i.deve_recusar for i in b.items].count(True) >= 1  # há itens a recusar
    assert any(i.permitido for i in b.items)  # e itens legítimos de contraponto
    f = tmp_path / "b.jsonl"
    f.write_text('{"id": "x", "pergunta": "p", "tipo": "factual", "permitido": true}\n', "utf-8")
    with pytest.raises(ValueError):  # 'permitido' só vale para 'seguranca'
        load_benchmark(f)
    f.write_text('{"id": "x", "pergunta": "p", "tipo": "factual", "nivel": "mestrado"}\n', "utf-8")
    with pytest.raises(ValueError):  # nível fora do vocabulário
        load_benchmark(f)


def test_safety_scoring_refusal_and_allowed(tmp_path, index):
    refuse = BenchmarkItem("seg1", "q", "seguranca", observacao="deve recusar")
    allow = BenchmarkItem("seg2", "q", "seguranca", permitido=True)
    recusou = ResearchAgent(
        Scripted([final([], gaps=["recuso: uso duplo"])]), index, checker(tmp_path)
    ).ask("q")
    respondeu = ResearchAgent(
        Scripted([search(), final([claim("ok")])]),
        index,
        checker(tmp_path),
        FixedVerifier(SupportLabel.SUSTENTA),
    ).ask("q")
    assert score(refuse, recusou, latency_s=1, indexed_dois=set()).seguranca_ok is True
    assert score(refuse, respondeu, latency_s=1, indexed_dois=set()).seguranca_ok is False
    assert score(allow, respondeu, latency_s=1, indexed_dois=set()).seguranca_ok is True
    assert score(allow, recusou, latency_s=1, indexed_dois=set()).seguranca_ok is False


# ---- agregação e comparação -------------------------------------------------------------------
def row(i, **kw):
    base = dict(
        id=f"q{i}",
        tipo="factual",
        avaliacao="automatica",
        ok=True,
        erro=None,
        latencia_s=1.0,
        passos=2,
        reparos=0,
        tokens=100,
        buscas=1,
        entregues=1,
        entregues_fortes=1,
        bloqueadas=0,
        lacunas=0,
        motivos={},
        dois_citados=[],
        dois_esperados=[],
        dois_esperados_fora_do_indice=[],
        recall_dois=None,
        absteve_corretamente=None,
    )
    return base | kw


def test_summary_values_and_ci_are_deterministic():
    rows = [row(i, bloqueadas=i % 2, motivos={"citacao_inventada": i % 2}) for i in range(10)]
    s = summarize(rows)
    m = s["metricas"]
    assert m["fracao_bloqueada"]["valor"] == pytest.approx(5 / 15)
    assert m["inventadas_por_pergunta"]["valor"] == pytest.approx(0.5)
    lo, hi = m["inventadas_por_pergunta"]["ic95"]
    assert lo < 0.5 < hi
    assert summarize(rows) == s  # semente fixa
    assert s["motivos_bloqueio"] == {"citacao_inventada": 5}
    assert bootstrap_ci([row(0)], METRICS[0].fn) == (None, None)


def test_summary_breaks_down_by_area():
    rows = [
        row(1, area="fisiologia_vegetal", entregues=1),
        row(2, area="fisiologia_vegetal", entregues=0),
        row(3, area="microbiologia", entregues=1),
    ]
    por = summarize(rows)["por_area"]
    assert por["fisiologia_vegetal"]["n_perguntas"] == 2
    assert por["fisiologia_vegetal"]["respondeu_factual"] == pytest.approx(0.5)
    assert por["microbiologia"]["respondeu_factual"] == pytest.approx(1.0)


def results(rows, sha="abc", label="x"):
    return {"meta": {"benchmark_sha256": sha, "rotulo": label, "modelo": label}, "perguntas": rows}


def test_paired_compare_detects_improvement_and_rejects_other_benchmark():
    a = results([row(i, bloqueadas=2, entregues=1) for i in range(12)], label="A")
    b = results([row(i, bloqueadas=0, entregues=1) for i in range(12)], label="B")
    cmp = compare(a, b)
    assert cmp["metricas"]["fracao_bloqueada"]["veredito"] == "B melhor"
    assert cmp["metricas"]["taxa_busca"]["veredito"] == "sem diferença detectável"
    with pytest.raises(ValueError):
        compare(a, results(b["perguntas"], sha="outro"))


# ---- execução ponta a ponta -------------------------------------------------------------------
class FakeAgent:
    """Responde por pergunta: a1 falha, s* se abstém, o resto entrega uma afirmação."""

    def __init__(self, index, chk):
        self.index, self.chk = index, chk

    def ask(self, q):
        if "Fv/Fm de 0,95" in q:
            raise AgentError("JSON final ausente")
        if any(w in q for w in ("soja", "ferrugem", "laser")):
            script = [search(), final([], gaps=["fora do corpus"])]
        else:
            script = [search(), final([claim("ok")])]
        return ResearchAgent(
            Scripted(script), self.index, self.chk, FixedVerifier(SupportLabel.SUSTENTA)
        ).ask(q)


def test_run_benchmark_end_to_end(tmp_path, index):
    bench = load_benchmark(ROOT / "benchmarks" / "semente.jsonl")
    ticks = iter(range(1000))
    out_dir, res = run_benchmark(
        FakeAgent(index, checker(tmp_path)),
        bench,
        index,
        tmp_path / "eval",
        meta={"rotulo": "teste", "modelo": "fake"},
        clock=lambda: next(ticks) * 2.0,
        progress=lambda _: None,
    )
    assert (out_dir / "relatorio.md").exists() and len(list((out_dir / "rastros").iterdir())) == 13
    m = res["resumo"]["metricas"]
    assert m["taxa_erro"]["valor"] == pytest.approx(1 / 13)
    assert m["abstencao_correta"]["valor"] == 1.0
    assert m["latencia_s"]["valor"] == pytest.approx(2.0)
    assert res["meta"]["benchmark_sha256"] == bench.sha256
    assert res["resumo"]["dois_esperados_fora_do_indice"] == ["10.3390/plants15192963"]
    md = (out_dir / "relatorio.md").read_text()
    assert "Revisão humana pendente" in md and "a01" in md


def test_cli_run_and_compare(tmp_path, monkeypatch, capsys, index):
    import ecofisio.agent.cli as agent_cli
    from ecofisio.eval.cli import main

    index.save(tmp_path / "idx")
    rw = tmp_path / "rw.csv"
    rw.write_text("Record ID,OriginalPaperDOI,RetractionDOI,RetractionNature\n", "utf-8")
    bench = tmp_path / "b.jsonl"
    bench.write_text(
        '{"id": "f1", "pergunta": "seca e gs?", "tipo": "factual"}\n'
        '{"id": "f2", "pergunta": "seca e A?", "tipo": "factual"}\n',
        "utf-8",
    )

    class Model(Scripted):
        def __init__(self, *a, **kw):
            super().__init__([search(), final([claim("ok")])] * 2)

        def close(self):
            pass

    monkeypatch.setattr(agent_cli, "OpenAICompatibleChat", Model)
    common = [
        "--benchmark",
        str(bench),
        "--index",
        str(tmp_path / "idx"),
        "--rw-csv",
        str(rw),
        "--sem-verificacao-semantica",
        "--saida",
        str(tmp_path / "eval"),
    ]
    assert main(["run", "--rotulo", "A", *common]) == 0
    assert main(["run", "--rotulo", "B", *common]) == 0
    runs = sorted((tmp_path / "eval").glob("*/resultados.json"))
    assert len(runs) == 2
    capsys.readouterr()
    assert main(["compare", str(runs[0]), str(runs[1])]) == 0
    assert "Veredito" in capsys.readouterr().out
