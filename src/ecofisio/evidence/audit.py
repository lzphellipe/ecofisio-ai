"""Auditoria de uma afirmação antes de ela chegar ao pesquisador.

Duas checagens por citação:
1. Retratação (CSV do Retraction Watch e/ou Crossref). Não verificado bloqueia.
2. Sustentação semântica (NLI): o trecho citado sustenta a afirmação?

Regra para a checagem semântica:
- RESULTADO_ISOLADO e CONSENSO: toda citação precisa SUSTENTAR; "contradiz" ou "não sustenta"
  bloqueia.
- CONTROVERSO: citações discordantes são esperadas (é o que torna o tema controverso); o resultado
  de cada uma vai para `warnings`, sem bloquear.
- ESPECULACAO: idem, só registro.
- Sem verificador configurado: bloqueia, a menos que `require_semantic=False` seja passado
  explicitamente. "Não verificado" nunca é tratado como "limpo".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ecofisio.evidence.models import Claim, EvidenceStrength
from ecofisio.evidence.retraction import RetractionChecker, RetractionStatus
from ecofisio.evidence.verify import SupportLabel, SupportVerifier, VerificationResult

_STRICT = {EvidenceStrength.RESULTADO_ISOLADO, EvidenceStrength.CONSENSO}
_VERB = {SupportLabel.CONTRADIZ: "contradiz", SupportLabel.NAO_SUSTENTA: "não sustenta"}


@dataclass(slots=True)
class AuditReport:
    claim: Claim
    retractions: dict[str, RetractionStatus] = field(default_factory=dict)
    support: list[tuple[str, VerificationResult]] = field(default_factory=list)  # (doi, resultado)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    semantic_check: str = "não executado"

    @property
    def blocked(self) -> bool:
        """True se a afirmação não pode ser entregue como está."""
        return bool(self.problems)


def audit_claim(
    claim: Claim,
    checker: RetractionChecker,
    verifier: SupportVerifier | None = None,
    *,
    require_semantic: bool = True,
) -> AuditReport:
    report = AuditReport(claim=claim)

    for doi in claim.dois:
        status = checker.check(doi)
        report.retractions[doi] = status
        if not status.checked:
            report.problems.append(f"{doi}: retratação não verificada ({status.error})")
        elif status.retracted:
            fontes = ", ".join(status.sources) or "fonte desconhecida"
            report.problems.append(f"{doi}: artigo retratado ({fontes})")

    if not claim.citations:
        report.semantic_check = "não aplicável (afirmação sem citação)"
        return report

    if verifier is None:
        report.semantic_check = "não executado (nenhum verificador configurado)"
        if require_semantic:
            report.problems.append("sustentação semântica não verificada")
        else:
            report.warnings.append(
                "sustentação semântica não verificada (dispensada pelo chamador)"
            )
        return report

    report.semantic_check = f"executado ({verifier.name})"
    strict = claim.strength in _STRICT
    for cit in claim.citations:
        res = verifier.verify(claim.text, cit.passage)
        report.support.append((cit.doi, res))
        if res.label is SupportLabel.SUSTENTA:
            continue
        msg = (
            f"{cit.doi} ({cit.page or 's/ localizador'}): trecho {_VERB[res.label]}"
            f" a afirmação (entailment={res.entailment:.2f}, contradição={res.contradiction:.2f})"
        )
        (report.problems if strict else report.warnings).append(msg)
    return report
