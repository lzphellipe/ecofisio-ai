"""Evidência verificável: citações, força da evidência, retratações e auditoria de afirmações."""

from ecofisio.evidence.audit import AuditReport, audit_claim
from ecofisio.evidence.models import (
    Citation,
    Claim,
    EpistemicStatus,
    EvidenceStrength,
    normalize_doi,
)
from ecofisio.evidence.retraction import (
    CrossrefClient,
    RetractionChecker,
    RetractionStatus,
    RetractionWatchIndex,
    parse_crossref_work,
)
from ecofisio.evidence.verify import (
    NLIVerifier,
    SupportLabel,
    SupportVerifier,
    VerificationResult,
)

__all__ = [
    "NLIVerifier",
    "SupportLabel",
    "SupportVerifier",
    "VerificationResult",
    "AuditReport",
    "Citation",
    "Claim",
    "CrossrefClient",
    "EpistemicStatus",
    "EvidenceStrength",
    "RetractionChecker",
    "RetractionStatus",
    "RetractionWatchIndex",
    "audit_claim",
    "normalize_doi",
    "parse_crossref_work",
]
