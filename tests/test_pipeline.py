"""Testes do pipeline. Os dados aqui são fabricados para exercitar as regras, não medições."""

import json

import numpy as np
import pandas as pd
import pytest

from ecofisio.pipeline import (
    DataLake,
    FluorescenceSchema,
    GasExchangeSchema,
    ProcessingLog,
    RawFileConflictError,
    SchemaStructureError,
    remove_outliers_mad,
    validate,
)


def gas_exchange(n: int = 12) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "sample_id": [f"s{i:02d}" for i in range(n)],
            "plant_id": [f"p{i % 4}" for i in range(n)],
            "treatment": ["controle" if i < n // 2 else "seca" for i in range(n)],
            "a": rng.normal(15, 1, n),
            "ci": rng.normal(280, 10, n),
            "gsw": rng.normal(0.3, 0.02, n),
            "tleaf": np.full(n, 25.0),
            "qin": np.full(n, 1500.0),
            "Flow": np.full(n, 500.0),  # coluna extra do equipamento: deve ser mantida
        }
    )


def test_valid_table_passes_untouched():
    log = ProcessingLog()
    good, bad = validate(gas_exchange(), GasExchangeSchema, log)
    assert len(good) == 12 and bad.empty and not log.entries
    assert "Flow" in good.columns


def test_invalid_rows_go_to_quarantine_with_reason_and_log():
    df = gas_exchange()
    df.loc[3, "a"] = 500.0  # fora da faixa
    df.loc[7, "gsw"] = -1.0
    log = ProcessingLog()
    good, bad = validate(df, GasExchangeSchema, log)
    assert set(bad["sample_id"]) == {"s03", "s07"}
    assert "a:" in bad.set_index("sample_id").at["s03", "rejection_reason"]
    assert len(good) == 10
    assert log.removed_ids == {"s03", "s07"}
    assert all(e.step == "validation" for e in log.entries)


def test_no_row_is_lost_between_valid_and_quarantine():
    df = gas_exchange()
    df.loc[[1, 2], "tleaf"] = 99.0
    good, bad = validate(df, GasExchangeSchema, ProcessingLog())
    assert len(good) + len(bad) == len(df)


def test_missing_required_column_raises():
    with pytest.raises(SchemaStructureError):
        validate(gas_exchange().drop(columns="ci"), GasExchangeSchema, ProcessingLog())


def test_fluorescence_rejects_fm_not_greater_than_f0():
    df = pd.DataFrame(
        {
            "sample_id": ["f1", "f2"],
            "plant_id": ["p1", "p2"],
            "treatment": ["c", "c"],
            "f0": [0.2, 0.5],
            "fm": [1.0, 0.4],
            "fv_fm": [0.8, 0.1],
        }
    )
    good, bad = validate(df, FluorescenceSchema, ProcessingLog())
    assert list(bad["sample_id"]) == ["f2"] and list(good["sample_id"]) == ["f1"]


def test_mad_removes_clear_outlier_and_logs_it():
    df = gas_exchange()
    df.loc[2, "a"] = 40.0
    log = ProcessingLog()
    kept, removed = remove_outliers_mad(df, "a", ["treatment"], log)
    assert list(removed["sample_id"]) == ["s02"]
    assert len(kept) == 11
    entry = log.entries[0]
    assert entry.affected_ids == ["s02"] and entry.details[0]["modified_z"] > 3.5


def test_mad_skips_small_groups_and_records_it():
    df = gas_exchange(6)  # grupos de 3: abaixo do mínimo
    df.loc[0, "a"] = 40.0
    log = ProcessingLog()
    kept, removed = remove_outliers_mad(df, "a", ["treatment"], log)
    assert removed.empty and len(kept) == 6
    assert len(log.entries[0].params["groups_not_filtered"]) == 2


def test_raw_ingest_is_immutable_and_idempotent(tmp_path):
    lake = DataLake(tmp_path / "lake")
    src = tmp_path / "medicao.csv"
    src.write_text("a,ci\n1,2\n")
    dest, digest = lake.ingest_raw(src)
    assert dest.read_text() == "a,ci\n1,2\n"
    assert dest.stat().st_mode & 0o222 == 0  # sem bit de escrita (root ignora, então testa o modo)
    assert lake.ingest_raw(src) == (dest, digest)  # mesmo arquivo: ok
    src.write_text("a,ci\n9,9\n")
    with pytest.raises(RawFileConflictError):
        lake.ingest_raw(src)


def test_layer_write_produces_traceable_manifest(tmp_path):
    lake = DataLake(tmp_path / "lake")
    log = ProcessingLog()
    good, _ = validate(gas_exchange(), GasExchangeSchema, log)
    out = lake.write(good, "validated", "trocas_gasosas", inputs=["abc123"], log=log)
    back = pd.read_parquet(out)
    assert len(back) == len(good)
    man = lake.read_manifest("validated", "trocas_gasosas")
    assert man["inputs"] == ["abc123"] and man["rows"] == len(good)
    assert len(man["sha256"]) == 64
    json.dumps(man)  # serializável


def test_raw_layer_cannot_be_written_as_parquet(tmp_path):
    lake = DataLake(tmp_path / "lake")
    with pytest.raises(ValueError):
        lake.write(gas_exchange(), "raw", "x", inputs=[])  # type: ignore[arg-type]
