"""Avaliação do assistente: benchmark versionado, métricas, intervalos e comparação."""

from ecofisio.eval.benchmark import Benchmark, BenchmarkItem, load_benchmark
from ecofisio.eval.metrics import QuestionResult, classify_reason, score
from ecofisio.eval.report import METRICS, bootstrap_ci, compare, summarize
from ecofisio.eval.runner import run_benchmark

__all__ = [
    "METRICS",
    "Benchmark",
    "BenchmarkItem",
    "QuestionResult",
    "bootstrap_ci",
    "classify_reason",
    "compare",
    "load_benchmark",
    "run_benchmark",
    "score",
    "summarize",
]
