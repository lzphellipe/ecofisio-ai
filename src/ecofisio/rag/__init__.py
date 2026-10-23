"""Busca na literatura (RAG): índice de trechos com BM25, embeddings opcionais e fusão RRF."""

from ecofisio.rag.bm25 import BM25, tokenize
from ecofisio.rag.embed import Embedder, SentenceTransformerEmbedder
from ecofisio.rag.index import Hit, LiteratureIndex, Passage

__all__ = [
    "BM25",
    "Embedder",
    "Hit",
    "LiteratureIndex",
    "Passage",
    "SentenceTransformerEmbedder",
    "tokenize",
]
