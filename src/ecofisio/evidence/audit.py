"""Auditoria de uma afirmação antes de ela chegar ao pesquisador.

Nesta versão a auditoria checa retratações e se cada DOI pôde ser verificado. A checagem de que
o trecho citado de fato sustenta a afirmação (verificação semântica) entra quando o RAG e o
modelo verificador existirem; até lá, `semantic_check` fica registrado como não executado em vez
de fingir que passou.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ecofisio.evidence.models import Claim
from ecofisio.evidence.retraction import RetractionChecker, RetractionStatus


@dataclass(slots=True)
class AuditReport:
    claim: Claim
    retractions: dict[str, RetractionStatus] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    semantic_check: str = "não executado (verificador semântico ainda não implementado)"

    @property
    def blocked(self) -> bool:
        """True se a afirmação não pode ser entregue como está."""
        return bool(self.problems)


def audit_claim(claim: Claim, checker: RetractionChecker) -> AuditReport:
    report = AuditReport(claim=claim)
    for doi in claim.dois:
        status = checker.check(doi)
        report.retractions[doi] = status
        if not status.checked:
            report.problems.append(f"{doi}: retratação não verificada ({status.error})")
        elif status.retracted:
            fontes = ", ".join(status.sources) or "fonte desconhecida"
            report.problems.append(f"{doi}: artigo retratado ({fontes})")
    return report
