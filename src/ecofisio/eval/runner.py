"""Executa um benchmark no agente e grava resultados, rastros e relatório."""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ecofisio.agent.llm import LLMError
from ecofisio.agent.research import AgentError, ResearchAgent
from ecofisio.eval.benchmark import Benchmark
from ecofisio.eval.metrics import score
from ecofisio.eval.report import render_markdown, summarize
from ecofisio.rag.index import LiteratureIndex


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")[:60] or "execucao"


def run_benchmark(
    agent: ResearchAgent,
    benchmark: Benchmark,
    index: LiteratureIndex,
    out_root: Path,
    *,
    meta: dict[str, Any],
    limit: int | None = None,
    clock: Callable[[], float] = time.perf_counter,
    progress: Callable[[str], None] = print,
) -> tuple[Path, dict[str, Any]]:
    """Roda cada pergunta, isolando falhas: um erro numa pergunta vira métrica, não aborta."""
    created = datetime.now(UTC)
    label = meta.get("rotulo") or meta.get("modelo") or "execucao"
    out_dir = out_root / f"{created:%Y%m%dT%H%M%SZ}_{_slug(label)}"
    (out_dir / "rastros").mkdir(parents=True, exist_ok=True)
    indexed_dois = {p.doi for p in index.passages if p.doi}
    items = benchmark.items[:limit] if limit else benchmark.items

    rows = []
    for n, item in enumerate(items, 1):
        t0 = clock()
        answer, error = None, None
        try:
            answer = agent.ask(item.pergunta)
        except (LLMError, AgentError) as exc:
            error = str(exc)[:300]
        elapsed = clock() - t0
        result = score(item, answer, latency_s=elapsed, indexed_dois=indexed_dois, error=error)
        rows.append(result.to_dict())
        trace = {"item": item.id, "pergunta": item.pergunta, "erro": error}
        if answer is not None:
            trace |= answer.to_dict()
        (out_dir / "rastros" / f"{_slug(item.id)}.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2), "utf-8"
        )
        r = result
        status = (
            f"erro: {error}"
            if error
            else f"{r.entregues} entregues, {r.bloqueadas} bloqueadas, {r.buscas} buscas"
        )
        progress(f"[{n}/{len(items)}] {item.id} ({elapsed:.1f}s): {status}")

    full_meta = {
        **meta,
        "criado_em": created.isoformat(),
        "benchmark": benchmark.path.name,
        "benchmark_sha256": benchmark.sha256,
        "corpus_sha256": index.corpus_hash(),
        "commit": _git_commit(),
        "limite": limit,
    }
    summary = summarize(rows)
    results = {"meta": full_meta, "resumo": summary, "perguntas": rows}
    (out_dir / "resultados.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), "utf-8"
    )
    (out_dir / "relatorio.md").write_text(render_markdown(full_meta, rows, summary), "utf-8")
    return out_dir, results
