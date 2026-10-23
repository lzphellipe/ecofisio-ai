"""Literatura científica: leitura de artigos JATS e cliente do Europe PMC."""

from ecofisio.literature.jats import (
    Article,
    Chunk,
    License,
    Paragraph,
    chunk_article,
    classify_license,
    parse_jats,
)

__all__ = [
    "Article",
    "Chunk",
    "License",
    "Paragraph",
    "chunk_article",
    "classify_license",
    "parse_jats",
]
