"""Gera o dataset de SFT por destilação: roda as sementes contra o LLM e escreve o JSONL.

    ecofisio-dataset --crossref-email voce@exemplo.org --sem-verificacao-semantica

Precisa de um LLM vivo (vLLM no Brev, Ollama etc.), como o ecofisio-ask. O índice DEVE ter sido
montado só com licenças de treino (CC BY/CC0) — ver --index e a doc de geração — para todo trecho
citado já ser liberado para fine-tuning.

Saída (pasta --out): train.jsonl, val.jsonl, manifest.json (contagens + DOIs + sha256) e
descartados.jsonl (perguntas que não passaram no portão, com o motivo, para inspeção).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ecofisio.agent.cli import add_agent_arguments, build_agent
from ecofisio.agent.llm import LLMError
from ecofisio.agent.research import AgentError
from ecofisio.dataset.distill import example_from_answer, manifest, split_train_val
from ecofisio.dataset.schema import SFTExample, dumps_jsonl
from ecofisio.dataset.seeds import REFUSAL_EXAMPLES, all_seeds


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    add_agent_arguments(ap)
    ap.add_argument("--out", type=Path, default=Path("data/sft"))
    ap.add_argument("--val-pct", type=int, default=15, help="fração para validação (padrão 15%%)")
    ap.add_argument(
        "--sem-recusas",
        action="store_true",
        help="não inclui os exemplos de recusa de uso duplo (padrão: inclui)",
    )
    ap.add_argument("--limite", type=int, default=None, help="usa só as N primeiras sementes")
    args = ap.parse_args(argv)

    agent, model, _ = build_agent(args, ap)
    seeds = all_seeds()[: args.limite] if args.limite else all_seeds()
    kept: list[SFTExample] = []
    discarded: list[dict] = []
    try:
        for seed in seeds:
            try:
                answer = agent.ask(seed.pergunta)
            except (LLMError, AgentError) as exc:
                discarded.append({"pergunta": seed.pergunta, "motivo": f"erro: {exc}"})
                continue
            example = example_from_answer(answer, seed)
            if example is None:
                motivo = (
                    f"portão: entregues={len(answer.delivered)} bloqueadas={len(answer.blocked)} "
                    f"reparos={answer.repairs} lacunas={len(answer.gaps)}"
                )
                discarded.append({"pergunta": seed.pergunta, "motivo": motivo})
            else:
                kept.append(example)
    finally:
        model.close()

    if not args.sem_recusas:
        kept.extend(REFUSAL_EXAMPLES)

    train, val = split_train_val(kept, args.val_pct)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "train.jsonl").write_text(dumps_jsonl(train), "utf-8")
    (args.out / "val.jsonl").write_text(dumps_jsonl(val), "utf-8")
    (args.out / "descartados.jsonl").write_text(
        "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in discarded), "utf-8"
    )
    man = manifest(kept)
    man["modelo_destilador"] = model.name
    man["n_treino"], man["n_validacao"] = len(train), len(val)
    man["n_descartados"] = len(discarded)
    man["sha256_treino"] = hashlib.sha256((args.out / "train.jsonl").read_bytes()).hexdigest()
    (args.out / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), "utf-8")

    print(f"{len(kept)} exemplos ({len(train)} treino, {len(val)} validação) em {args.out}")
    print(f"descartados: {len(discarded)}")
    for tipo, n in man["por_tipo"].items():
        print(f"  {n:4d}  {tipo}")
    if not kept:
        print("nada passou no portão: confira se o LLM está respondendo e o índice tem conteúdo.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
