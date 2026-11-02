"""Configuração do QLoRA. Padrões conservadores para o Qwen3-4B numa GPU de 24 GB (L4/3090)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# módulos lineares do Qwen3 onde o LoRA entra (atenção + MLP)
ALVOS_QWEN = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")


@dataclass(slots=True)
class TrainConfig:
    modelo_base: str = "Qwen/Qwen3-4B"
    dados: str = "data/sft/train.jsonl"
    validacao: str | None = "data/sft/val.jsonl"
    saida: str = "outputs/qlora"

    # LoRA
    r: int = 16
    alpha: int = 32
    dropout: float = 0.05
    alvos: tuple[str, ...] = ALVOS_QWEN
    quatro_bits: bool = True  # QLoRA: pesos base em 4 bits

    # treino
    lr: float = 2e-4
    epocas: float = 3.0
    batch: int = 1
    acumulo: int = 16  # batch efetivo = batch * acumulo
    max_tokens: int = 4096
    warmup: float = 0.03
    seed: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["alvos"] = list(self.alvos)
        return d

    @classmethod
    def from_json(cls, path: Path) -> TrainConfig:
        bruto = json.loads(Path(path).read_text("utf-8"))
        if "alvos" in bruto:
            bruto["alvos"] = tuple(bruto["alvos"])
        campos = {f for f in cls.__slots__}  # type: ignore[attr-defined]
        desconhecidos = set(bruto) - campos
        if desconhecidos:
            raise ValueError(f"config: campos desconhecidos {sorted(desconhecidos)}")
        return cls(**bruto)

    def salvar(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), "utf-8")
