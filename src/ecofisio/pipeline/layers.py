"""Camadas de dados: raw → validated → processed → analytics.

- raw: cópia byte a byte do arquivo do equipamento, imutável, identificada pelo SHA-256.
- validated / processed / analytics: Parquet + manifesto JSON com hash, origem e log.

Qualquer número da camada analytics pode ser rastreado até o arquivo bruto pelos manifestos.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from ecofisio.pipeline.log import ProcessingLog

Layer = Literal["validated", "processed", "analytics"]
LAYERS: tuple[str, ...] = ("raw", "validated", "processed", "analytics")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class RawFileConflictError(FileExistsError):
    """Já existe um arquivo bruto com o mesmo nome e conteúdo diferente."""


@dataclass(frozen=True, slots=True)
class DataLake:
    root: Path

    def __post_init__(self) -> None:
        for layer in LAYERS:
            (self.root / layer).mkdir(parents=True, exist_ok=True)

    def path(self, layer: str, name: str) -> Path:
        if layer not in LAYERS:
            raise ValueError(f"camada desconhecida: {layer}")
        return self.root / layer / name

    def ingest_raw(self, source: Path) -> tuple[Path, str]:
        """Copia o arquivo para raw/ sem alterar nada. Retorna (caminho, sha256).

        Reingerir o mesmo arquivo é idempotente; um arquivo diferente com o mesmo nome é recusado
        para nunca sobrescrever dado bruto.
        """
        digest = sha256_file(source)
        dest = self.path("raw", source.name)
        if dest.exists():
            if sha256_file(dest) != digest:
                raise RawFileConflictError(
                    f"{dest.name} já existe em raw/ com conteúdo diferente; renomeie o arquivo novo"
                )
            return dest, digest
        shutil.copy2(source, dest)
        dest.chmod(0o444)  # somente leitura
        return dest, digest

    def write(
        self,
        df: pd.DataFrame,
        layer: Layer,
        name: str,
        *,
        inputs: list[str],
        log: ProcessingLog | None = None,
    ) -> Path:
        """Grava `df` em Parquet na camada e o manifesto ao lado. `inputs` = hashes de origem."""
        if layer == "raw":
            raise ValueError("raw só recebe arquivos via ingest_raw")
        out = self.path(layer, f"{name}.parquet")
        df.to_parquet(out, index=False)
        manifest = {
            "name": name,
            "layer": layer,
            "rows": int(len(df)),
            "columns": list(map(str, df.columns)),
            "sha256": sha256_file(out),
            "inputs": inputs,
            "created_at": datetime.now(UTC).isoformat(),
            "processing_log": log.to_records() if log else [],
        }
        out.with_suffix(".manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8"
        )
        return out

    def read_manifest(self, layer: Layer, name: str) -> dict:
        return json.loads(self.path(layer, f"{name}.manifest.json").read_text("utf-8"))
