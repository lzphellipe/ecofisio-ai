"""Estruturas de evidência: toda afirmação do assistente é um `Claim` com citações verificáveis.

Convenções do projeto (não são padrão externo; ajuste se o grupo decidir diferente):
- ESPECULACAO é a única força que pode sair sem citação.
- CONSENSO exige ao menos 2 DOIs distintos: um artigo só não faz consenso.
- Cada citação traz o trecho exato que sustenta a afirmação, não só a referência.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:")


class EvidenceStrength(StrEnum):
    CONSENSO = "consenso"
    RESULTADO_ISOLADO = "resultado_isolado"
    CONTROVERSO = "controverso"
    ESPECULACAO = "especulacao"


class EpistemicStatus(StrEnum):
    MEDIDO = "medido"  # observado diretamente no estudo citado
    INFERIDO = "inferido"  # conclusão derivada, do estudo ou do assistente


def normalize_doi(doi: str) -> str:
    """Forma canônica: sem prefixo de URL, minúsculas (DOIs não diferenciam caixa)."""
    s = doi.strip()
    for p in _DOI_PREFIXES:
        if s.lower().startswith(p):
            s = s[len(p) :]
            break
    s = s.lower()
    if not _DOI_RE.match(s):
        raise ValueError(f"DOI inválido: {doi!r}")
    return s


@dataclass(frozen=True, slots=True)
class Citation:
    doi: str
    passage: str  # trecho do artigo que sustenta a afirmação
    page: str | None = None  # página ou seção ("p. 4", "Results")

    def __post_init__(self) -> None:
        object.__setattr__(self, "doi", normalize_doi(self.doi))
        if not self.passage.strip():
            raise ValueError(f"citação de {self.doi} sem trecho: o trecho é obrigatório")


@dataclass(slots=True)
class Claim:
    text: str
    strength: EvidenceStrength
    status: EpistemicStatus
    citations: list[Citation] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("afirmação vazia")
        if self.strength is not EvidenceStrength.ESPECULACAO and not self.citations:
            raise ValueError(f"força '{self.strength}' exige ao menos uma citação")
        if self.strength is EvidenceStrength.CONSENSO and len({c.doi for c in self.citations}) < 2:
            raise ValueError("consenso exige ao menos 2 DOIs distintos")

    @property
    def dois(self) -> list[str]:
        return sorted({c.doi for c in self.citations})
