"""Validação de esquema: separa linhas válidas das inválidas sem perder nenhuma.

Linhas inválidas não somem: vão para um DataFrame de quarentena com o motivo, e cada uma gera
entrada no log. Erros que tornam a tabela inteira inválida (coluna obrigatória ausente) levantam
exceção, porque não há como validar parcialmente.
"""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa

from ecofisio.pipeline.log import LogEntry, ProcessingLog


class SchemaStructureError(ValueError):
    """A tabela não tem a estrutura mínima do esquema (ex.: coluna obrigatória ausente)."""


def validate(
    df: pd.DataFrame, schema: type[pa.DataFrameModel], log: ProcessingLog
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retorna (válidas, quarentena). A quarentena tem a coluna `rejection_reason`."""
    if "sample_id" not in df.columns:
        raise SchemaStructureError("coluna obrigatória ausente: sample_id")
    df = df.reset_index(drop=True)
    try:
        valid = schema.validate(df, lazy=True)
        return valid, df.iloc[0:0].assign(rejection_reason=pd.Series(dtype=str))
    except pa.errors.SchemaErrors as err:
        cases = err.failure_cases

    structural = cases[cases["index"].isna()]
    if not structural.empty:
        msgs = "; ".join(
            f"{c.column}: {c.check}" for c in structural.itertuples() if c.column is not None
        ) or "; ".join(str(c) for c in structural["check"])
        raise SchemaStructureError(f"tabela fora do esquema {schema.__name__}: {msgs}")

    cases = cases.assign(index=cases["index"].astype(int))
    reasons = (
        cases.assign(
            msg=cases["column"].fillna("linha").astype(str) + ": " + cases["check"].astype(str)
        )
        .groupby("index")["msg"]
        .agg(lambda s: "; ".join(sorted(set(s))))
    )
    bad_idx = reasons.index.to_numpy()
    quarantine = df.loc[bad_idx].assign(rejection_reason=reasons.loc[bad_idx].to_numpy())
    good = df.drop(index=bad_idx)

    for check, grp in cases.groupby(["column", "check"], dropna=False):
        col, rule = check
        ids = df.loc[sorted(set(grp["index"])), "sample_id"].astype(str).tolist()
        log.add(
            LogEntry(
                step="validation",
                rule=f"{col}: {rule}",
                affected_ids=ids,
                reason=f"violação do esquema {schema.__name__}",
                details=[
                    {"sample_id": str(df.at[i, "sample_id"]), "value": _jsonable(v)}
                    for i, v in zip(grp["index"], grp["failure_case"], strict=True)
                ],
            )
        )

    # Revalida o que sobrou: garante tipos coagidos e que nada inválido passou.
    return schema.validate(good, lazy=True), quarantine


def _jsonable(value: object) -> object:
    try:
        return value.item()  # tipos NumPy
    except AttributeError:
        return value if isinstance(value, (int, float, str, bool, type(None))) else str(value)
