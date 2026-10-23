"""Cliente do Europe PMC para buscar artigos abertos e baixar o texto completo em JATS.

Endpoints usados (confirmados em documentação de terceiros que consome a API, ver README):
- busca:        GET {BASE}search?query=...&format=json&pageSize=...&cursorMark=...
- texto em XML: GET {BASE}{PMCID}/fullTextXML

O formato da resposta JSON da busca (`resultList.result[]`, `nextCursorMark`) segue o padrão da
API, mas não pôde ser testado ao vivo no ambiente onde este código foi escrito; o parser é
tolerante e `scripts/smoke_europepmc.py` mostra as chaves reais. Rode-o antes de um download
grande.

A licença NÃO é decidida aqui: é lida do próprio XML em `parse_jats`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/"


@dataclass(frozen=True, slots=True)
class SearchHit:
    pmcid: str | None
    doi: str | None
    title: str
    is_open_access: bool | None
    raw: dict[str, Any]


def _parse_hit(r: dict[str, Any]) -> SearchHit:
    oa = r.get("isOpenAccess")
    return SearchHit(
        pmcid=(r.get("pmcid") or None),
        doi=(r.get("doi") or None),
        title=str(r.get("title") or ""),
        is_open_access=None if oa is None else str(oa).upper() in {"Y", "TRUE"},
        raw=r,
    )


class EuropePMCClient:
    """Busca paginada por cursor, download de fullTextXML com cache em disco e limite de taxa.

    O cache é escrito uma vez por PMCID e marcado como somente leitura: é a camada raw do texto.
    """

    def __init__(
        self,
        cache_dir: Path,
        *,
        email: str | None = None,
        min_interval_s: float = 0.2,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._email = email
        self._min_interval = min_interval_s
        self._sleep, self._clock = sleep, clock
        self._last = float("-inf")
        self._http = httpx.Client(
            base_url=BASE,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": "ecofisio-ai/0.1 (literature corpus)"},
            follow_redirects=True,
        )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        wait = self._min_interval - (self._clock() - self._last)
        if wait > 0:
            self._sleep(wait)
        self._last = self._clock()
        params = dict(params or {})
        if self._email:
            params["email"] = self._email
        return self._http.get(path, params=params)

    def search_page(
        self, query: str, *, cursor: str = "*", page_size: int = 100
    ) -> tuple[list[SearchHit], str | None]:
        resp = self._get(
            "search",
            {"query": query, "format": "json", "pageSize": page_size, "cursorMark": cursor},
        )
        resp.raise_for_status()
        data = resp.json()
        results = (data.get("resultList") or {}).get("result") or []
        nxt = data.get("nextCursorMark")
        return [_parse_hit(r) for r in results], (nxt if nxt and nxt != cursor else None)

    def search(
        self, query: str, *, max_results: int = 100, page_size: int = 100
    ) -> Iterator[SearchHit]:
        """Itera os resultados até `max_results`, seguindo o cursor."""
        cursor: str | None = "*"
        seen = 0
        while cursor is not None and seen < max_results:
            hits, cursor = self.search_page(
                query, cursor=cursor, page_size=min(page_size, max_results - seen)
            )
            if not hits:
                return
            for h in hits:
                yield h
                seen += 1
                if seen >= max_results:
                    return

    def full_text_xml(self, pmcid: str) -> bytes | None:
        """XML JATS do artigo; None se o Europe PMC não tiver texto completo para ele."""
        pmcid = pmcid.upper()
        if not pmcid.startswith("PMC") or not pmcid[3:].isdigit():
            raise ValueError(f"PMCID inválido: {pmcid}")
        cached = self.cache_dir / f"{pmcid}.xml"
        if cached.exists():
            return cached.read_bytes()
        resp = self._get(f"{pmcid}/fullTextXML")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        cached.write_bytes(resp.content)
        cached.chmod(0o444)
        return resp.content

    def close(self) -> None:
        self._http.close()
