"""Checagem de retratações antes de qualquer citação.

Duas fontes:

1. Índice offline do CSV do Retraction Watch (distribuído pela Crossref). Colunas documentadas
   pela Crossref: `OriginalPaperDOI` (artigo retratado) e `RetractionDOI` (aviso de retratação).
   `RetractionNature` e `Record ID` são usados se existirem; confira contra o CSV baixado.
2. API REST da Crossref, `GET /v1/works/{DOI}`. A documentação da Crossref diz que retratações
   aparecem no campo `update-to` (itens com `type: "retraction"` e `source` igual a
   "publisher" ou "retraction-watch"). Ela NÃO deixa claro se esse campo vem no registro do
   artigo retratado ou só no do aviso; por isso este código é conservador: qualquer item de
   retratação em `update-to` ou `updated-by` marca o DOI como retratado. Um falso positivo
   (o DOI ser o próprio aviso) bloqueia uma citação que não deveria ser usada como evidência
   de qualquer forma.

Se nenhuma fonte responder, o status sai com `checked=False`: quem chama não pode tratar
"não verificado" como "limpo".
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ecofisio.evidence.models import normalize_doi

CROSSREF_WORKS = "https://api.crossref.org/v1/works/"


@dataclass(slots=True)
class RetractionStatus:
    doi: str
    checked: bool
    retracted: bool = False
    sources: list[str] = field(default_factory=list)
    notice_dois: list[str] = field(default_factory=list)
    record_ids: list[str] = field(default_factory=list)
    error: str | None = None


class RetractionWatchIndex:
    """Índice em memória do CSV do Retraction Watch, por DOI do artigo original."""

    def __init__(self, rows: dict[str, list[dict[str, str]]]) -> None:
        self._rows = rows

    @classmethod
    def from_csv(cls, path: Path, *, only_retractions: bool = True) -> RetractionWatchIndex:
        rows: dict[str, list[dict[str, str]]] = {}
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or "OriginalPaperDOI" not in reader.fieldnames:
                raise ValueError(f"{path.name}: coluna OriginalPaperDOI não encontrada")
            for r in reader:
                nature = (r.get("RetractionNature") or "").strip().lower()
                if only_retractions and nature and nature != "retraction":
                    continue  # correções e "expression of concern" ficam de fora
                try:
                    doi = normalize_doi(r.get("OriginalPaperDOI") or "")
                except ValueError:
                    continue  # linhas sem DOI válido (o CSV tem casos assim)
                rows.setdefault(doi, []).append(r)
        return cls(rows)

    def __len__(self) -> int:
        return len(self._rows)

    def lookup(self, doi: str) -> RetractionStatus:
        key = normalize_doi(doi)
        hits = self._rows.get(key, [])
        return RetractionStatus(
            doi=key,
            checked=True,
            retracted=bool(hits),
            sources=["retraction-watch-csv"] if hits else [],
            notice_dois=sorted(
                {h["RetractionDOI"].lower() for h in hits if h.get("RetractionDOI")}
            ),
            record_ids=sorted({h["Record ID"] for h in hits if h.get("Record ID")}),
        )


def parse_crossref_work(doi: str, message: dict[str, Any]) -> RetractionStatus:
    """Interpreta o `message` de /v1/works/{DOI} (ver regra conservadora no topo do módulo)."""
    key = normalize_doi(doi)
    entries = [
        e
        for fld in ("update-to", "updated-by")
        for e in (message.get(fld) or [])
        if str(e.get("type", "")).lower() == "retraction"
    ]
    return RetractionStatus(
        doi=key,
        checked=True,
        retracted=bool(entries),
        sources=sorted({f"crossref:{e.get('source', 'unknown')}" for e in entries}),
        notice_dois=sorted({str(e["DOI"]).lower() for e in entries if e.get("DOI")} - {key}),
        record_ids=sorted({str(e["record-id"]) for e in entries if e.get("record-id") is not None}),
    )


class CrossrefClient:
    """Cliente mínimo da API da Crossref com cache em memória.

    `mailto` coloca as requisições no "polite pool" da Crossref; informe um e-mail de contato
    do projeto (não pessoal) ao rodar em lote.
    """

    def __init__(
        self,
        mailto: str | None = None,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        params = {"mailto": mailto} if mailto else {}
        self._http = httpx.Client(
            base_url=CROSSREF_WORKS,
            params=params,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": "ecofisio-ai/0.1 (retraction check)"},
        )
        self._cache: dict[str, RetractionStatus] = {}

    def check(self, doi: str) -> RetractionStatus:
        key = normalize_doi(doi)
        if key in self._cache:
            return self._cache[key]
        try:
            resp = self._http.get(key)
        except httpx.HTTPError as exc:
            return RetractionStatus(doi=key, checked=False, error=f"rede: {exc}")
        if resp.status_code == 404:
            status = RetractionStatus(
                doi=key, checked=False, error="DOI não encontrado na Crossref"
            )
        elif resp.status_code != 200:
            return RetractionStatus(doi=key, checked=False, error=f"HTTP {resp.status_code}")
        else:
            status = parse_crossref_work(key, resp.json().get("message", {}))
        self._cache[key] = status
        return status

    def close(self) -> None:
        self._http.close()


class RetractionChecker:
    """Combina o índice offline e a API. Retratado em qualquer fonte = retratado."""

    def __init__(
        self, index: RetractionWatchIndex | None = None, client: CrossrefClient | None = None
    ) -> None:
        if index is None and client is None:
            raise ValueError("informe ao menos uma fonte: índice CSV ou cliente Crossref")
        self.index = index
        self.client = client

    def check(self, doi: str) -> RetractionStatus:
        results = [
            s
            for s in (
                self.index.lookup(doi) if self.index is not None else None,
                self.client.check(doi) if self.client is not None else None,
            )
            if s is not None
        ]
        checked = [s for s in results if s.checked]
        merged = RetractionStatus(doi=normalize_doi(doi), checked=bool(checked))
        merged.retracted = any(s.retracted for s in checked)
        for s in checked:
            merged.sources += s.sources
            merged.notice_dois += s.notice_dois
            merged.record_ids += s.record_ids
        merged.sources = sorted(set(merged.sources))
        merged.notice_dois = sorted(set(merged.notice_dois))
        merged.record_ids = sorted(set(merged.record_ids))
        if not checked:
            merged.error = "; ".join(s.error or "sem resposta" for s in results)
        return merged
