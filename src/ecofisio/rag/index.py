"""Índice de literatura: trechos de artigos com busca lexical, densa ou híbrida.

Híbrido = BM25 + embeddings fundidos por Reciprocal Rank Fusion (Cormack, Clarke & Büttcher,
2009, SIGIR), com k = 60 como no artigo original. RRF combina rankings sem calibrar escalas de
score diferentes, o que o torna um padrão robusto; o ganho sobre BM25 puro ainda precisa ser
medido no nosso benchmark antes de virar padrão definitivo.

Todo resultado sabe virar `Citation` (DOI + trecho + seção), que é o que a auditoria de evidência
consome. Trechos de artigos sem DOI ficam fora da busca por padrão: não dá para citá-los.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np

from ecofisio.evidence.models import Citation
from ecofisio.literature.jats import Article, License, chunk_article
from ecofisio.rag.bm25 import BM25, tokenize
from ecofisio.rag.embed import Embedder

RRF_K = 60
# Tipos JATS de pesquisa original. Revisões sintetizam evidência (úteis, mas secundárias);
# editoriais e comentários são opinião.
PRIMARY_TYPES = frozenset({"research-article", "brief-report", "rapid-communication"})
Mode = Literal["lexical", "dense", "hybrid"]


@dataclass(frozen=True, slots=True)
class Passage:
    chunk_id: str
    doi: str | None
    pmcid: str | None
    title: str
    year: int | None
    section: str
    license: str
    text: str
    article_type: str = ""  # JATS article-type; "" em índices antigos (anteriores ao campo)

    @property
    def citable(self) -> bool:
        return self.doi is not None

    @property
    def primary_evidence(self) -> bool:
        """Editorial, revisão, comentário etc. não são resultado experimental primário."""
        return self.article_type in PRIMARY_TYPES


@dataclass(frozen=True, slots=True)
class Hit:
    passage: Passage
    score: float
    lexical_rank: int | None
    dense_rank: int | None

    def to_citation(self) -> Citation:
        if self.passage.doi is None:
            raise ValueError(f"{self.passage.chunk_id}: artigo sem DOI não pode ser citado")
        return Citation(doi=self.passage.doi, passage=self.passage.text, page=self.passage.section)

    def as_tool_result(self) -> dict[str, Any]:
        """Formato entregue ao LLM pela ferramenta de busca."""
        p = self.passage
        return {
            "doi": p.doi,
            "title": p.title,
            "year": p.year,
            "section": p.section,
            "license": p.license,
            "article_type": p.article_type or "desconhecido",
            "primary_evidence": p.primary_evidence,
            "text": p.text,
            "score": round(self.score, 6),
        }


def _hash_records(records) -> str:
    h = hashlib.sha256()
    for r in records:
        h.update(json.dumps(r, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()


class LiteratureIndex:
    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder
        self.passages: list[Passage] = []
        self._keys: set[str] = set()
        self._bm25: BM25 | None = None
        self._emb: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self.passages)

    def add_article(self, article: Article, **chunk_kw: int) -> int:
        """Adiciona os trechos do artigo. Retorna quantos entraram (0 se já estava no índice)."""
        key = article.doi or article.key
        if key in self._keys:
            return 0
        self._keys.add(key)
        new = [
            Passage(
                chunk_id=c.chunk_id,
                doi=c.doi,
                pmcid=article.pmcid,
                title=article.title,
                year=article.year,
                section=c.section,
                license=str(article.license),
                text=c.text,
                article_type=article.article_type,
            )
            for c in chunk_article(article, **chunk_kw)
        ]
        self.passages.extend(new)
        self._bm25 = None
        self._emb = None
        return len(new)

    def build(self) -> None:
        texts = [f"{p.title}. {p.section}. {p.text}" for p in self.passages]
        self._bm25 = BM25([tokenize(t) for t in texts])
        if self.embedder is not None:
            self._emb = self.embedder.encode_passages(texts) if texts else np.zeros((0, 0))

    def _ensure_built(self) -> None:
        if self._bm25 is None or (self.embedder is not None and self._emb is None):
            self.build()

    def search(
        self,
        query: str,
        k: int = 5,
        *,
        mode: Mode = "hybrid",
        candidates: int = 50,
        citable_only: bool = True,
        licenses: set[License] | None = None,
    ) -> list[Hit]:
        if not query.strip():
            raise ValueError("consulta vazia")
        if mode != "lexical" and self.embedder is None:
            if mode == "dense":
                raise ValueError("busca densa sem embedder configurado")
            mode = "lexical"  # híbrido sem embedder degrada para lexical, sem fingir
        self._ensure_built()
        n = len(self.passages)
        if n == 0:
            return []
        allowed = np.ones(n, dtype=bool)
        if citable_only:
            allowed &= np.array([p.citable for p in self.passages], dtype=bool)
        if licenses is not None:
            names = {str(lic) for lic in licenses}
            allowed &= np.array([p.license in names for p in self.passages], dtype=bool)

        def ranking(scores: np.ndarray) -> list[int]:
            order = np.argsort(-scores, kind="stable")
            return [int(i) for i in order if allowed[i] and scores[i] > 0][:candidates]

        lex = ranking(self._bm25.scores(tokenize(query))) if mode != "dense" else []
        den: list[int] = []
        if mode != "lexical":
            sims = self._emb @ self.embedder.encode_query(query)
            # cosseno pode ser ≤ 0; desloca para o filtro "> 0" só excluir os não permitidos
            den = ranking(sims - sims.min() + 1e-9)

        lex_rank = {i: r for r, i in enumerate(lex, 1)}
        den_rank = {i: r for r, i in enumerate(den, 1)}
        fused: dict[int, float] = {}
        for ranks in (lex_rank, den_rank):
            for i, r in ranks.items():
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + r)
        top = sorted(fused, key=lambda i: (-fused[i], i))[:k]
        return [Hit(self.passages[i], fused[i], lex_rank.get(i), den_rank.get(i)) for i in top]

    # ---- persistência -------------------------------------------------------------------
    def corpus_hash(self) -> str:
        return _hash_records(asdict(p) for p in self.passages)

    def save(self, directory: Path) -> None:
        self._ensure_built()
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "passages.jsonl").open("w", encoding="utf-8") as f:
            for p in self.passages:
                f.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")
        if self._emb is not None:
            np.save(directory / "embeddings.npy", self._emb)
        licenses: dict[str, int] = {}
        for p in self.passages:
            licenses[p.license] = licenses.get(p.license, 0) + 1
        meta = {
            "passages": len(self.passages),
            "articles": len(self._keys),
            "embedder": self.embedder.name if self.embedder else None,
            "corpus_sha256": self.corpus_hash(),
            "passages_by_license": licenses,
            "built_at": datetime.now(UTC).isoformat(),
        }
        (directory / "meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), "utf-8"
        )

    @classmethod
    def load(cls, directory: Path, embedder: Embedder | None = None) -> LiteratureIndex:
        meta = json.loads((directory / "meta.json").read_text("utf-8"))
        idx = cls(embedder)
        with (directory / "passages.jsonl").open(encoding="utf-8") as f:
            records = [json.loads(line) for line in f]
        # o hash é conferido sobre os registros como estão no arquivo, para índices salvos antes
        # de um campo novo continuarem carregando (o campo novo entra com o valor padrão)
        if _hash_records(records) != meta["corpus_sha256"]:
            raise ValueError("passages.jsonl não bate com o hash do meta.json (arquivo alterado?)")
        idx.passages = [Passage(**r) for r in records]
        idx._keys = {p.doi or p.pmcid or p.title for p in idx.passages}
        idx._bm25 = BM25([tokenize(f"{p.title}. {p.section}. {p.text}") for p in idx.passages])
        emb_path = directory / "embeddings.npy"
        if embedder is not None:
            if meta["embedder"] != embedder.name or not emb_path.exists():
                raise ValueError(
                    f"índice foi construído com embedder={meta['embedder']!r}, "
                    f"não {embedder.name!r}: reconstrua"
                )
            idx._emb = np.load(emb_path)
        return idx
