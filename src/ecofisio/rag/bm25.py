"""BM25 (Robertson & Zaragoza, 2009) sem dependências além de NumPy.

Variante de IDF do Lucene, ln(1 + (N − df + 0,5)/(df + 0,5)), que nunca fica negativa. Sem
stemming: termos técnicos como "fv/fm", "co2" e "a/ci" valem mais intactos do que reduzidos.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

import numpy as np
from numpy.typing import NDArray

_TOKEN = re.compile(r"[a-z0-9]+(?:[/'\-][a-z0-9]+)*")
_STOP = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the this to was were "
    "with which these those than then there their been being into also not no can may".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.doc_len = np.array([len(d) for d in docs], dtype=np.float64)
        self.avgdl = float(self.doc_len.mean()) if self.n else 0.0
        postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, d in enumerate(docs):
            for term, tf in Counter(d).items():
                postings[term].append((i, tf))
        self._post: dict[str, tuple[NDArray[np.int64], NDArray[np.float64]]] = {
            t: (np.array([p[0] for p in ps]), np.array([p[1] for p in ps], dtype=np.float64))
            for t, ps in postings.items()
        }
        self._idf = {
            t: math.log(1.0 + (self.n - len(ids) + 0.5) / (len(ids) + 0.5))
            for t, (ids, _) in self._post.items()
        }

    def scores(self, query: list[str]) -> NDArray[np.float64]:
        out = np.zeros(self.n)
        if not self.n:
            return out
        norm = self.k1 * (1.0 - self.b + self.b * self.doc_len / max(self.avgdl, 1e-9))
        for term in set(query):
            if term not in self._post:
                continue
            ids, tf = self._post[term]
            out[ids] += self._idf[term] * tf * (self.k1 + 1.0) / (tf + norm[ids])
        return out
