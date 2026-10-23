"""Fachada Python dos kernels C++.

O resto do código importa daqui, nunca de `ecofisio._kernels` diretamente: assim a conversão de
tipos e a validação ficam num só lugar, e o kernel pode ser trocado (CPU, CUDA) sem mexer nos
chamadores.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray

from ecofisio.physio.fvcb import FvCBConstants, FvCBParams

try:
    from ecofisio import _kernels
except ImportError as exc:  # pragma: no cover - só ocorre sem o pacote compilado
    raise ImportError(
        "O módulo C++ ecofisio._kernels não está compilado. Instale com `pip install -e .` "
        "(compila via scikit-build-core) antes de usar ecofisio.kernels."
    ) from exc


def fvcb_batch(
    ci: ArrayLike,
    curve: ArrayLike,
    params: Sequence[FvCBParams],
    constants: Sequence[FvCBConstants],
) -> tuple[NDArray[np.float64], NDArray[np.int8]]:
    """Avalia o FvCB em lote: `ci[i]` pertence à curva `curve[i]` (índice em `params`)."""
    if len(params) != len(constants):
        raise ValueError(f"{len(params)} conjuntos de parâmetros e {len(constants)} de constantes")

    def col(values: list[float]) -> NDArray[np.float64]:
        return np.ascontiguousarray(values, dtype=np.float64)

    return _kernels.fvcb_net_assimilation_batch(
        np.ascontiguousarray(ci, dtype=np.float64).ravel(),
        np.ascontiguousarray(curve, dtype=np.int64).ravel(),
        col([p.vcmax for p in params]),
        col([p.j for p in params]),
        col([p.rd for p in params]),
        col([p.tpu for p in params]),
        col([c.gamma_star for c in constants]),
        col([c.km for c in constants]),
    )
