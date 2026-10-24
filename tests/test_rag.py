"""Índice de literatura. Artigos fictícios (DOIs 10.5555), embedder falso e determinístico."""

import hashlib
from pathlib import Path

import numpy as np
import pytest

from ecofisio.literature import Article, License, Paragraph, parse_jats
from ecofisio.rag import BM25, LiteratureIndex, tokenize

FIXTURE = Path(__file__).parent / "fixtures" / "jats_cc_by.xml"


class HashEmbedder:
    """Bag-of-words com hashing: suficiente para testar a mecânica, sem baixar modelo."""

    name = "hash-test-v1"

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(64, dtype=np.float32)
        for t in tokenize(text):
            v[int(hashlib.md5(t.encode()).hexdigest(), 16) % 64] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def encode_passages(self, texts):
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, 64), np.float32)

    def encode_query(self, text):
        return self._vec(text)


def art(doi, title, paras, lic=License.CC_BY, pmcid=None):
    return Article(
        pmcid=pmcid,
        doi=doi,
        title=title,
        year=2023,
        journal=None,
        license=lic,
        license_source="test",
        paragraphs=[Paragraph(s, t) for s, t in paras],
    )


@pytest.fixture
def corpus():
    return [
        parse_jats(FIXTURE.read_bytes()),
        art(
            "10.5555/nitrogen",
            "Leaf nitrogen and Rubisco",
            [
                ("Results", "Leaf nitrogen content correlated with Rubisco activity and Vcmax."),
            ],
        ),
        art(
            "10.5555/proline",
            "Proline accumulation",
            [
                ("Results", "Proline accumulated in leaves under osmotic stress."),
            ],
            lic=License.CC_BY_NC,
        ),
        art(None, "Preprint without DOI", [("Body", "Stomatal conductance drought response.")]),
    ]


def test_bm25_prefers_documents_with_rare_query_terms():
    docs = [tokenize(t) for t in ["vcmax drought coffee", "drought soil", "rain soil soil"]]
    s = BM25(docs).scores(tokenize("vcmax drought"))
    assert s[0] > s[1] > s[2] == 0.0


def test_tokenizer_keeps_technical_terms():
    assert {"fv/fm", "co2", "a/ci"} <= set(tokenize("Fv/Fm, CO2 and A/Ci curves"))


def test_lexical_search_returns_citable_passage(corpus):
    idx = LiteratureIndex()
    for a in corpus:
        idx.add_article(a)
    hits = idx.search("stomatal conductance drought", k=3, mode="lexical")
    assert hits and hits[0].passage.doi == "10.5555/test.drought.001"
    assert all(h.passage.doi for h in hits)  # o preprint sem DOI fica de fora
    cit = hits[0].to_citation()
    assert cit.doi == "10.5555/test.drought.001" and cit.page.startswith("Results")


def test_license_filter(corpus):
    idx = LiteratureIndex()
    for a in corpus:
        idx.add_article(a)
    hits = idx.search("proline leaves stress", k=5, licenses={License.CC_BY, License.CC0})
    assert all(h.passage.license == "CC-BY" for h in hits)
    assert not any(h.passage.doi == "10.5555/proline" for h in hits)


def test_hybrid_without_embedder_degrades_to_lexical(corpus):
    idx = LiteratureIndex()
    for a in corpus:
        idx.add_article(a)
    hybrid = idx.search("Rubisco nitrogen", k=2)
    lexical = idx.search("Rubisco nitrogen", k=2, mode="lexical")
    assert [h.passage.chunk_id for h in hybrid] == [h.passage.chunk_id for h in lexical]
    with pytest.raises(ValueError):
        idx.search("x", mode="dense")


def test_hybrid_fuses_both_rankings(corpus):
    idx = LiteratureIndex(HashEmbedder())
    for a in corpus:
        idx.add_article(a)
    hits = idx.search("Rubisco nitrogen Vcmax", k=3)
    top = hits[0]
    assert top.passage.doi == "10.5555/nitrogen"
    assert top.lexical_rank is not None and top.dense_rank is not None
    assert top.score == pytest.approx(1 / (60 + top.lexical_rank) + 1 / (60 + top.dense_rank))


def test_duplicate_article_is_ignored(corpus):
    idx = LiteratureIndex()
    assert idx.add_article(corpus[1]) > 0
    assert idx.add_article(corpus[1]) == 0


def test_save_load_roundtrip_and_tamper_detection(tmp_path, corpus):
    idx = LiteratureIndex(HashEmbedder())
    for a in corpus:
        idx.add_article(a)
    idx.save(tmp_path / "idx")
    loaded = LiteratureIndex.load(tmp_path / "idx", HashEmbedder())
    q = "drought assimilation"
    assert [h.passage.chunk_id for h in loaded.search(q)] == [
        h.passage.chunk_id for h in idx.search(q)
    ]

    lines = (tmp_path / "idx" / "passages.jsonl").read_text().splitlines()
    lines[0] = lines[0].replace("40%", "90%")
    (tmp_path / "idx" / "passages.jsonl").write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError):
        LiteratureIndex.load(tmp_path / "idx")


def test_load_rejects_different_embedder(tmp_path, corpus):
    idx = LiteratureIndex(HashEmbedder())
    idx.add_article(corpus[1])
    idx.save(tmp_path / "idx")

    class Other(HashEmbedder):
        name = "other"

    with pytest.raises(ValueError):
        LiteratureIndex.load(tmp_path / "idx", Other())


def test_tool_result_shape(corpus):
    idx = LiteratureIndex()
    idx.add_article(corpus[1])
    r = idx.search("Rubisco")[0].as_tool_result()
    assert set(r) == {
        "doi",
        "title",
        "year",
        "section",
        "license",
        "article_type",
        "primary_evidence",
        "text",
        "score",
    }


def test_empty_query_rejected():
    with pytest.raises(ValueError):
        LiteratureIndex().search("  ")


def test_empty_index_returns_no_hits():
    assert LiteratureIndex(HashEmbedder()).search("drought") == []
    assert LiteratureIndex().search("drought", mode="lexical") == []


def test_article_type_flows_to_passages_and_tool_result(corpus):
    idx = LiteratureIndex()
    idx.add_article(corpus[0])  # fixture JATS: research-article
    hit = idx.search("stomatal conductance drought")[0]
    assert hit.passage.article_type == "research-article" and hit.passage.primary_evidence
    assert hit.as_tool_result()["primary_evidence"] is True


def test_index_saved_before_article_type_still_loads(tmp_path, corpus):
    import json

    idx = LiteratureIndex()
    idx.add_article(corpus[1])
    idx.save(tmp_path / "idx")
    # simula um índice antigo: registros sem o campo article_type, hash recalculado sobre eles
    lines = (tmp_path / "idx" / "passages.jsonl").read_text().splitlines()
    old = [{k: v for k, v in json.loads(x).items() if k != "article_type"} for x in lines]
    (tmp_path / "idx" / "passages.jsonl").write_text("\n".join(json.dumps(r) for r in old) + "\n")
    from ecofisio.rag.index import _hash_records

    meta = json.loads((tmp_path / "idx" / "meta.json").read_text())
    meta["corpus_sha256"] = _hash_records(old)
    (tmp_path / "idx" / "meta.json").write_text(json.dumps(meta))
    loaded = LiteratureIndex.load(tmp_path / "idx")
    assert loaded.passages[0].article_type == "" and not loaded.passages[0].primary_evidence
