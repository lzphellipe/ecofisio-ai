"""Registro de tudo que o pipeline tira ou muda nos dados.

Regra do projeto: nenhum dado é removido ou alterado sem uma entrada aqui dizendo o quê, por qual
regra, com quais parâmetros e quando. O log viaja junto com o dataset no manifesto da camada.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class LogEntry:
    step: str  # ex.: "validation", "outliers_mad"
    rule: str  # regra legível, ex.: "a >= -20"
    affected_ids: list[str]  # sample_id das linhas afetadas
    reason: str
    params: dict[str, Any] = field(default_factory=dict)
    details: list[dict[str, Any]] = field(default_factory=list)  # valor, z-score, etc. por linha
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def n_rows(self) -> int:
        return len(self.affected_ids)


@dataclass(slots=True)
class ProcessingLog:
    entries: list[LogEntry] = field(default_factory=list)

    def add(self, entry: LogEntry) -> None:
        self.entries.append(entry)

    @property
    def removed_ids(self) -> set[str]:
        return {i for e in self.entries for i in e.affected_ids}

    def to_records(self) -> list[dict[str, Any]]:
        return [{**asdict(e), "n_rows": e.n_rows} for e in self.entries]

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_records(), ensure_ascii=False, indent=2), "utf-8")
