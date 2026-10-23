"""Testes do módulo de evidência. DOIs com prefixo 10.5555 (prefixo de teste da Crossref)."""

import httpx
import pytest

from ecofisio.evidence import (
    Citation,
    Claim,
    CrossrefClient,
    EpistemicStatus,
    EvidenceStrength,
    RetractionChecker,
    RetractionWatchIndex,
    SupportLabel,
    VerificationResult,
    audit_claim,
    normalize_doi,
    parse_crossref_work,
)
from ecofisio.evidence.verify import decide, label_indices

OK = "10.5555/ok.1"
OK2 = "10.5555/ok.2"
BAD = "10.5555/retratado.1"


def cite(doi: str) -> Citation:
    return Citation(doi=doi, passage="Vcmax decreased under drought.", page="p. 4")


@pytest.mark.parametrize("raw", ["https://doi.org/10.5555/ABC", "doi:10.5555/abc", " 10.5555/abc "])
def test_normalize_doi(raw):
    assert normalize_doi(raw) == "10.5555/abc"


def test_invalid_doi_rejected():
    with pytest.raises(ValueError):
        normalize_doi("not-a-doi")


def test_citation_requires_passage():
    with pytest.raises(ValueError):
        Citation(doi=OK, passage="   ")


def test_non_speculative_claim_requires_citation():
    with pytest.raises(ValueError):
        Claim("A cai sob seca.", EvidenceStrength.RESULTADO_ISOLADO, EpistemicStatus.MEDIDO)
    Claim(
        "Talvez o efeito dependa da espécie.",
        EvidenceStrength.ESPECULACAO,
        EpistemicStatus.INFERIDO,
    )


def test_consensus_requires_two_distinct_dois():
    with pytest.raises(ValueError):
        Claim("x", EvidenceStrength.CONSENSO, EpistemicStatus.MEDIDO, [cite(OK), cite(OK)])
    Claim("x", EvidenceStrength.CONSENSO, EpistemicStatus.MEDIDO, [cite(OK), cite(OK2)])


def rw_csv(tmp_path):
    p = tmp_path / "rw.csv"
    p.write_text(
        "Record ID,OriginalPaperDOI,RetractionDOI,RetractionNature\n"
        f"101,{BAD.upper()},10.5555/aviso.1,Retraction\n"
        f"102,{OK2},10.5555/correcao.1,Correction\n"
        "103,,10.5555/sem-doi,Retraction\n",
        encoding="utf-8",
    )
    return RetractionWatchIndex.from_csv(p)


def test_csv_index_finds_retraction_and_ignores_corrections(tmp_path):
    idx = rw_csv(tmp_path)
    s = idx.lookup(BAD)
    assert s.retracted and s.record_ids == ["101"] and s.notice_dois == ["10.5555/aviso.1"]
    assert not idx.lookup(OK2).retracted  # correção não é retratação
    assert len(idx) == 1


def test_csv_without_required_column_is_rejected(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError):
        RetractionWatchIndex.from_csv(p)


def test_parse_crossref_update_to_retraction():
    msg = {
        "update-to": [
            {
                "DOI": "10.5555/aviso.1",
                "type": "retraction",
                "source": "retraction-watch",
                "record-id": 44124,
            }
        ]
    }
    s = parse_crossref_work(BAD, msg)
    assert s.retracted and s.sources == ["crossref:retraction-watch"] and s.record_ids == ["44124"]


def test_parse_crossref_ignores_non_retraction_updates():
    msg = {"update-to": [{"DOI": "10.5555/err", "type": "correction", "source": "publisher"}]}
    assert not parse_crossref_work(OK, msg).retracted


def mock_client(status: int = 200, payload: dict | None = None, raise_exc: bool = False):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        if raise_exc:
            raise httpx.ConnectError("sem rede")
        return httpx.Response(status, json={"message": payload or {}})

    return CrossrefClient(
        mailto="projeto@example.org", transport=httpx.MockTransport(handler)
    ), calls


def test_crossref_client_caches_and_sends_mailto():
    client, calls = mock_client(payload={"update-to": []})
    assert not client.check(OK).retracted
    client.check(OK)
    assert len(calls) == 1
    assert "mailto=projeto%40example.org" in str(calls[0])
    assert str(calls[0]).startswith("https://api.crossref.org/v1/works/10.5555/ok.1")


def test_network_failure_is_unchecked_not_clean():
    client, _ = mock_client(raise_exc=True)
    s = client.check(OK)
    assert not s.checked and s.error


def test_audit_blocks_retracted_and_unverified(tmp_path):
    checker = RetractionChecker(index=rw_csv(tmp_path))
    claim = Claim("x", EvidenceStrength.CONSENSO, EpistemicStatus.MEDIDO, [cite(OK), cite(BAD)])
    report = audit_claim(claim, checker)
    assert report.blocked
    assert any("retratado" in p for p in report.problems)

    offline, _ = mock_client(raise_exc=True)
    report = audit_claim(
        Claim("y", EvidenceStrength.RESULTADO_ISOLADO, EpistemicStatus.MEDIDO, [cite(OK)]),
        RetractionChecker(client=offline),
    )
    assert report.blocked and "não verificada" in report.problems[0]


def test_audit_without_verifier_blocks_unless_explicitly_waived(tmp_path):
    claim = Claim("x", EvidenceStrength.RESULTADO_ISOLADO, EpistemicStatus.MEDIDO, [cite(OK)])
    checker = RetractionChecker(index=rw_csv(tmp_path))

    report = audit_claim(claim, checker)
    assert report.blocked
    assert report.semantic_check.startswith("não executado")

    waived = audit_claim(claim, checker, require_semantic=False)
    assert not waived.blocked and waived.warnings


class FakeVerifier:
    """Rótulo fixo por DOI: testa só a regra de bloqueio, não a qualidade do NLI."""

    name = "fake-nli"

    def __init__(self, labels):
        self.labels = labels

    def verify(self, claim, passage):
        lab = self.labels[passage]
        return VerificationResult(lab, 0.9 if lab is SupportLabel.SUSTENTA else 0.1, 0.8, self.name)


def claim_with(strength, *passages):
    cits = [Citation(doi=f"10.5555/ok.{i}", passage=p) for i, p in enumerate(passages, 1)]
    return Claim("Drought reduces Vcmax.", strength, EpistemicStatus.MEDIDO, cits)


def test_strict_claim_blocked_when_a_passage_does_not_support(tmp_path):
    checker = RetractionChecker(index=rw_csv(tmp_path))
    v = FakeVerifier({"p1": SupportLabel.SUSTENTA, "p2": SupportLabel.NAO_SUSTENTA})
    report = audit_claim(claim_with(EvidenceStrength.CONSENSO, "p1", "p2"), checker, v)
    assert report.blocked
    assert len(report.problems) == 1 and "10.5555/ok.2" in report.problems[0]
    assert "não sustenta" in report.problems[0]
    assert report.semantic_check == "executado (fake-nli)"
    assert len(report.support) == 2


def test_strict_claim_passes_when_all_passages_support(tmp_path):
    checker = RetractionChecker(index=rw_csv(tmp_path))
    v = FakeVerifier({"p1": SupportLabel.SUSTENTA})
    report = audit_claim(claim_with(EvidenceStrength.RESULTADO_ISOLADO, "p1"), checker, v)
    assert not report.blocked and not report.warnings


def test_controversial_claim_records_contradiction_without_blocking(tmp_path):
    checker = RetractionChecker(index=rw_csv(tmp_path))
    v = FakeVerifier({"p1": SupportLabel.SUSTENTA, "p2": SupportLabel.CONTRADIZ})
    report = audit_claim(claim_with(EvidenceStrength.CONTROVERSO, "p1", "p2"), checker, v)
    assert not report.blocked
    assert any("contradiz" in w for w in report.warnings)


def test_label_indices_read_from_model_config():
    assert label_indices({0: "contradiction", 1: "entailment", 2: "neutral"}) == {
        "contradiction": 0,
        "entailment": 1,
        "neutral": 2,
    }
    assert label_indices({0: "ENTAILMENT", 1: "NOT_ENTAILMENT"}) == {
        "entailment": 0,
        "not_entailment": 1,
    }
    with pytest.raises(ValueError):
        label_indices({0: "positive", 1: "negative"})


@pytest.mark.parametrize(
    ("e", "c", "expected"),
    [
        (0.8, 0.1, SupportLabel.SUSTENTA),
        (0.2, 0.7, SupportLabel.CONTRADIZ),
        (0.3, 0.3, SupportLabel.NAO_SUSTENTA),
    ],
)
def test_decide_thresholds(e, c, expected):
    assert decide(e, c, min_entailment=0.5, min_contradiction=0.5) is expected
