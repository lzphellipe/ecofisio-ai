"""Embeddings densos (opcional). Sem eles, o índice funciona só com BM25.

O corpus é quase todo em inglês e as perguntas podem vir em português, então um modelo
multilíngue é a escolha natural. A família E5 multilíngue exige os prefixos "query: " e
"passage: " (convenção documentada pelos autores do E5); outros modelos podem não usar prefixo.
Confira o model card do modelo escolhido e ajuste `query_prefix`/`passage_prefix`.

Rodar em GPU (RTX 4090 / L4) só compensa para corpora grandes; para alguns milhares de trechos a
CPU resolve. Siga a regra de custo do projeto antes de alugar GPU para isso.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
from numpy.typing import NDArray


class Embedder(Protocol):
    name: str

    def encode_passages(self, texts: list[str]) -> NDArray[np.float32]: ...

    def encode_query(self, text: str) -> NDArray[np.float32]: ...


class SentenceTransformerEmbedder:
    """Wrapper de `sentence-transformers` (extra `rag`). Vetores normalizados: produto = cosseno."""

    def __init__(
        self,
        model_name: str,
        *,
        query_prefix: str = "",
        passage_prefix: str = "",
        device: str | None = None,
        batch_size: int = 32,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - depende do extra instalado
            raise ImportError("instale o extra: pip install -e '.[rag]'") from exc
        self.name = model_name
        self._model = SentenceTransformer(model_name, device=device)
        self._qp, self._pp, self._bs = query_prefix, passage_prefix, batch_size

    def _encode(self, texts: list[str]) -> NDArray[np.float32]:
        vecs = self._model.encode(
            texts, batch_size=self._bs, normalize_embeddings=True, show_progress_bar=False
        )
        return np.asarray(vecs, dtype=np.float32)

    def encode_passages(self, texts: list[str]) -> NDArray[np.float32]:
        return self._encode([self._pp + t for t in texts])

    def encode_query(self, text: str) -> NDArray[np.float32]:
        return self._encode([self._qp + text])[0]
