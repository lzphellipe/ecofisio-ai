"""Avalia o assistente num conjunto de perguntas e compara execuções.

    ecofisio-eval run --benchmark benchmarks/semente.jsonl --rotulo qwen3-4b-cpu \\
        --crossref-email contato@exemplo.org --sem-verificacao-semantica
    ecofisio-eval compare runs/eval/<A>/resultados.json runs/eval/<B>/resultados.json

Aceita as mesmas opções de modelo do ecofisio-ask (--base-url, --model, --pensar...).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ecofisio.agent.cli import add_agent_arguments, build_agent
from ecofisio.eval.benchmark import load_benchmark
from ecofisio.eval.report import compare, render_comparison
from ecofisio.eval.runner import run_benchmark


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="roda o benchmark")
    run.add_argument("--benchmark", type=Path, default=Path("benchmarks/semente.jsonl"))
    run.add_argument("--rotulo", default=None, help="nome curto da configuração, ex.: qwen3-4b-cpu")
    run.add_argument("--saida", type=Path, default=Path("runs/eval"))
    run.add_argument("--limite", type=int, default=None, help="roda só as N primeiras perguntas")
    add_agent_arguments(run)

    cmp_ = sub.add_parser("compare", help="compara duas execuções (B − A)")
    cmp_.add_argument("a", type=Path)
    cmp_.add_argument("b", type=Path)

    args = ap.parse_args(argv)
    if args.cmd == "compare":
        a = json.loads(args.a.read_text("utf-8"))
        b = json.loads(args.b.read_text("utf-8"))
        try:
            result = compare(a, b)
        except ValueError as exc:
            ap.error(str(exc))
        print(render_comparison(a, b, result))
        return 0

    benchmark = load_benchmark(args.benchmark)
    agent, model, index = build_agent(args, run)
    meta = {
        "rotulo": args.rotulo,
        "modelo": args.model,
        "base_url": args.base_url,
        "pensar": args.pensar,
        "max_passos": args.max_passos,
        "verificacao_semantica": args.nli_model
        or ("dispensada" if args.sem_verificacao_semantica else "ausente (bloqueia)"),
    }
    try:
        out_dir, results = run_benchmark(
            agent, benchmark, index, args.saida, meta=meta, limit=args.limite
        )
    finally:
        model.close()
    print((out_dir / "relatorio.md").read_text("utf-8"))
    print(f"Resultados em {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
