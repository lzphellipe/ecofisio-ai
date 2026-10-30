"""Construção do dataset de SFT (fase 2) por destilação do agente base + corpus."""

from ecofisio.dataset.distill import (
    example_from_answer,
    manifest,
    split_train_val,
)
from ecofisio.dataset.schema import SFTExample, dumps_jsonl
from ecofisio.dataset.seeds import (
    REFUSAL_EXAMPLES,
    SeedQuestion,
    all_seeds,
)

__all__ = [
    "REFUSAL_EXAMPLES",
    "SFTExample",
    "SeedQuestion",
    "all_seeds",
    "dumps_jsonl",
    "example_from_answer",
    "manifest",
    "split_train_val",
]
