"""ecofisio-train — ajusta o modelo base com QLoRA sobre o dataset de SFT.

    ecofisio-train --dados data/sft/train.jsonl --so-estimar      # só a estimativa de custo
    ecofisio-train --dados data/sft/train.jsonl --sim             # treina (confirma com --sim)

Antes de treinar, mostra as estatísticas do dataset e a estimativa de GPU-horas/custo e PEDE
confirmação (regra do projeto: nada de job de GPU sem confirmar). O treino em si precisa de GPU
e das dependências de `.[train]`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ecofisio.training.config import TrainConfig
from ecofisio.training.custo import estimar_custo, resumo_humano
from ecofisio.training.prepare import carregar_sft, estatisticas


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dados", type=Path, default=Path("data/sft/train.jsonl"))
    ap.add_argument("--config", type=Path, default=None, help="config JSON (opcional)")
    ap.add_argument("--modelo-base", default=None, help="sobrepõe o modelo base da config")
    ap.add_argument("--epocas", type=float, default=None)
    ap.add_argument("--saida", type=Path, default=None)
    ap.add_argument("--brl", type=float, default=None, help="cotação R$/US$ para mostrar em reais")
    ap.add_argument("--so-estimar", action="store_true", help="mostra estatística e custo e sai")
    ap.add_argument("--sim", action="store_true", help="confirma o treino sem perguntar")
    args = ap.parse_args(argv)

    cfg = TrainConfig.from_json(args.config) if args.config else TrainConfig()
    if args.modelo_base:
        cfg.modelo_base = args.modelo_base
    if args.epocas is not None:
        cfg.epocas = args.epocas
    if args.saida is not None:
        cfg.saida = str(args.saida)
    cfg.dados = str(args.dados)

    try:
        exemplos = carregar_sft(args.dados)
    except (FileNotFoundError, ValueError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    est = estatisticas(args.dados)
    custo = estimar_custo(len(exemplos), cfg.epocas)
    print(f"Dataset: {len(exemplos)} exemplos  ({args.dados})")
    print(f"  por tipo:  {est['por_tipo']}")
    print(f"  por área:  {est['por_area']}")
    print(f"Modelo base: {cfg.modelo_base}  ·  épocas: {cfg.epocas}  ·  saída: {cfg.saida}")
    print(f"Estimativa de GPU: {resumo_humano(custo, args.brl)}")
    print("  (ordem de grandeza; depende da GPU e do tamanho real dos exemplos)")

    if args.so_estimar:
        return 0

    if len(exemplos) < 20:
        print(
            f"AVISO: só {len(exemplos)} exemplos — muito pouco para um fine-tuning útil. "
            "Amplie o corpus e as sementes e regenere o dataset antes de treinar de verdade."
        )

    if not args.sim:
        resp = input("Confirmar o treino na GPU? (s/N) ").strip().lower()
        if resp not in ("s", "sim", "y", "yes"):
            print("cancelado.")
            return 1

    from ecofisio.training.train import treinar  # importa torch etc. só aqui

    saida = treinar(cfg, exemplos)
    print(f"adaptador salvo em {saida}")
    print(
        "Próximo: sirva o base + adaptador e rode `ecofisio-eval compare` contra o base + RAG "
        "para ver se o ajuste melhorou (critério de aceite do projeto)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
