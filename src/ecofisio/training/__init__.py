"""Fase 3 — fine-tuning (QLoRA) do modelo base sobre o dataset de SFT.

O fine-tuning ensina COMPORTAMENTO (citar, calibrar, recusar, chamar ferramentas), não fatos —
os fatos continuam vindo do RAG. Por isso o critério de aceite é superar o "base + RAG" no
benchmark (ecofisio-eval), não decorar literatura.
"""

from ecofisio.training.config import TrainConfig
from ecofisio.training.custo import estimar_custo
from ecofisio.training.prepare import carregar_sft, estatisticas

__all__ = ["TrainConfig", "carregar_sft", "estatisticas", "estimar_custo"]
