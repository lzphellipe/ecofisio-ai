"""Estimativa grosseira de GPU-horas e custo do treino, para confirmar antes de gastar.

Regra do projeto (CLAUDE.md): antes de qualquer job de GPU, estimar GPU, horas e custo e pedir
confirmação. A estimativa é ORDEM DE GRANDEZA — serve para decidir, não para orçar com precisão.
"""

from __future__ import annotations

import math
from typing import Any


def estimar_custo(
    n_exemplos: int,
    epocas: float,
    *,
    tokens_por_exemplo: int = 1500,
    tokens_por_s: float = 2000.0,  # ~QLoRA de um 4B numa L4; ajuste conforme a GPU
    usd_por_hora: float = 0.90,  # L4 no Brev
    overhead: float = 1.3,  # carga do modelo, checkpoints, avaliação
) -> dict[str, Any]:
    """Devolve tokens totais, horas e custo estimados (ordem de grandeza)."""
    if n_exemplos < 0 or epocas <= 0 or tokens_por_s <= 0:
        raise ValueError("parâmetros inválidos para a estimativa")
    tokens = n_exemplos * tokens_por_exemplo * epocas
    horas = (tokens / tokens_por_s) / 3600.0 * overhead
    horas = max(horas, 0.05)  # piso: carga do modelo já leva minutos
    return {
        "tokens": int(tokens),
        "horas": round(horas, 2),
        "usd": round(horas * usd_por_hora, 2),
        "premissas": {
            "tokens_por_exemplo": tokens_por_exemplo,
            "tokens_por_s": tokens_por_s,
            "usd_por_hora": usd_por_hora,
            "overhead": overhead,
        },
    }


def resumo_humano(est: dict[str, Any], brl_por_usd: float | None = None) -> str:
    linha = f"~{est['tokens']:,} tokens · ~{est['horas']} h de GPU · ~US$ {est['usd']:.2f}".replace(
        ",", "."
    )
    if brl_por_usd:
        linha += f" (~R$ {math.ceil(est['usd'] * brl_por_usd)})"
    return linha
