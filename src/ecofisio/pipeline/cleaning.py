"""Limpeza de dados com registro obrigatório.

Nenhuma função daqui imputa valores: o projeto proíbe completar dados experimentais. O que sai
vai para um DataFrame de removidos e para o log.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from ecofisio.pipeline.log import LogEntry, ProcessingLog

# Iglewicz & Hoaglin (1993), "How to Detect and Handle Outliers": z modificado com MAD,
# limiar 3,5. Critério robusto e muito usado; ainda assim é uma regra estatística, não
# fisiológica — revise os removidos antes de aceitar.
MAD_SCALE = 0.6745
DEFAULT_THRESHOLD = 3.5


def modified_z(values: pd.Series) -> pd.Series:
    """z modificado = 0,6745·(x − mediana)/MAD. NaN quando MAD = 0 (sem dispersão)."""
    med = values.median()
    mad = (values - med).abs().median()
    if mad == 0 or np.isnan(mad):
        return pd.Series(np.nan, index=values.index)
    return MAD_SCALE * (values - med) / mad


def remove_outliers_mad(
    df: pd.DataFrame,
    column: str,
    group_cols: Sequence[str],
    log: ProcessingLog,
    threshold: float = DEFAULT_THRESHOLD,
    min_group_size: int = 5,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Remove outliers de `column` por grupo (ex.: tratamento). Retorna (mantidos, removidos).

    Grupos com menos de `min_group_size` linhas ou MAD = 0 não são filtrados, e isso também é
    registrado: com poucos pontos o critério não é confiável.
    """
    if column not in df.columns:
        raise KeyError(f"coluna inexistente: {column}")
    z = pd.Series(np.nan, index=df.index)
    skipped: list[str] = []
    for key, grp in df.groupby(list(group_cols), dropna=False):
        if len(grp) < min_group_size:
            skipped.append(f"{key} (n={len(grp)})")
            continue
        gz = modified_z(grp[column])
        if gz.isna().all():
            skipped.append(f"{key} (MAD=0)")
        z.loc[grp.index] = gz

    mask = z.abs() > threshold
    removed = df[mask].assign(modified_z=z[mask])
    kept = df[~mask]
    log.add(
        LogEntry(
            step="outliers_mad",
            rule=f"|z modificado de {column}| > {threshold} por {list(group_cols)}",
            affected_ids=removed["sample_id"].astype(str).tolist(),
            reason="outlier robusto (Iglewicz & Hoaglin 1993)",
            params={
                "column": column,
                "group_cols": list(group_cols),
                "threshold": threshold,
                "min_group_size": min_group_size,
                "groups_not_filtered": skipped,
            },
            details=[
                {
                    "sample_id": str(r.sample_id),
                    "value": float(getattr(r, column)),
                    "modified_z": float(r.modified_z),
                }
                for r in removed.itertuples()
            ],
        )
    )
    return kept, removed
