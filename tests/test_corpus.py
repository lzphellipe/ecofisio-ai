"""Montagem do corpus de ponta a ponta com a API simulada."""

from pathlib import Path

import httpx

from ecofisio.literature import License
from ecofisio.literature.corpus import build_corpus, main
from ecofisio.literature.europepmc import EuropePMCClient
from ecofisio.rag import LiteratureIndex

XML = (Path(__file__).parent / "fixtures" / "jats_cc_by.xml").read_bytes()
NC_XML = (
    XML.replace(b"licenses/by/4.0", b"licenses/by-nc/4.0")
    .replace(b"PMC0000001", b"PMC0000003")
    .replace(b"TEST.DROUGHT.001", b"TEST.NC.003")
)


def handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path
    if p.endswith("/search"):
        return httpx.Response(
            200,
            json={
                "nextCursorMark": "*",
                "resultList": {
                    "result": [
                        {"pmcid": "PMC0000001", "doi": "10.5555/test.drought.001", "title": "OK"},
                        {"doi": "10.5555/sem.pmc", "title": "sem PMCID"},
                        {"pmcid": "PMC0000002", "title": "sem texto"},
                        {"pmcid": "PMC0000003", "title": "NC"},
                        {"pmcid": "PMC0000004", "title": "XML ruim"},
                    ]
                },
            },
        )
    if p.endswith("PMC0000001/fullTextXML"):
        return httpx.Response(200, content=XML)
    if p.endswith("PMC0000003/fullTextXML"):
        return httpx.Response(200, content=NC_XML)
    if p.endswith("PMC0000004/fullTextXML"):
        return httpx.Response(200, content=b"<html>erro</html>")
    return httpx.Response(404)


def client(tmp_path):
    return EuropePMCClient(
        tmp_path / "raw", transport=httpx.MockTransport(handler), min_interval_s=0
    )


def test_every_hit_gets_a_status(tmp_path):
    idx = LiteratureIndex()
    report = build_corpus(client(tmp_path), "q", idx, max_articles=10)
    status = {e.title: e.status for e in report}
    assert status["OK"] == "indexado"
    assert status["sem PMCID"].startswith("sem PMCID")
    assert status["sem texto"] == "sem fullTextXML"
    assert status["NC"] == "indexado"
    assert status["XML ruim"].startswith("XML inválido")
    nc = next(e for e in report if e.title == "NC")
    assert nc.license == "CC-BY-NC" and not nc.training_allowed
    assert len(idx) > 0


def test_license_filter_excludes_and_records(tmp_path):
    idx = LiteratureIndex()
    report = build_corpus(
        client(tmp_path), "q", idx, max_articles=10, allowed_licenses={License.CC_BY, License.CC0}
    )
    nc = next(e for e in report if e.title == "NC")
    assert nc.status.startswith("licença fora do filtro")
    assert all(p.license == "CC-BY" for p in idx.passages)


def test_cli_writes_index_and_report(tmp_path, monkeypatch, capsys):
    import ecofisio.literature.corpus as corpus_mod

    real = corpus_mod.EuropePMCClient
    monkeypatch.setattr(
        corpus_mod,
        "EuropePMCClient",
        lambda raw, email=None: real(
            raw, email=email, transport=httpx.MockTransport(handler), min_interval_s=0
        ),
    )
    out = tmp_path / "lit"
    main(["--query", "q", "--max", "5", "--out", str(out), "--raw", str(tmp_path / "raw")])
    assert (out / "passages.jsonl").exists() and (out / "meta.json").exists()
    assert len((out / "corpus_report.jsonl").read_text().splitlines()) == 5
    assert "artigos encontrados" in capsys.readouterr().out
    loaded = LiteratureIndex.load(out)
    assert loaded.search("stomatal conductance drought")


def test_query_file_ignores_comments_and_bom(tmp_path):
    from ecofisio.literature.corpus import read_query_file

    f = tmp_path / "q.txt"
    f.write_text('﻿# comentário\n("a b" OR c)\n\n  AND d\n', encoding="utf-8")
    assert read_query_file(f) == '("a b" OR c) AND d'


def test_repo_query_file_is_valid():
    from ecofisio.literature.corpus import read_query_file

    q = read_query_file(Path(__file__).parents[1] / "queries" / "seca_trocas_gasosas.txt")
    assert q.startswith('("stomatal conductance"') and q.endswith("OPEN_ACCESS:y")
