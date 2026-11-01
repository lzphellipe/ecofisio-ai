"""Armazenamento simples em arquivo para projetos e artefatos (no estilo do runs/).

Dois arquivos JSON numa pasta que persiste no disco da VM entre liga/desliga:
- projetos.json: projetos nomeados, cada um com a lista de ids de perguntas (rastros em runs/).
- artefatos.json: respostas favoritadas, cada uma apontando para um id de pergunta.

Baixa concorrência (uso de duas pessoas): leitura-modificação-escrita direta, sem trava.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _agora() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class AppStore:
    dir: Path

    def __post_init__(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    def _ler(self, nome: str, chave: str) -> list[dict[str, Any]]:
        f = self.dir / nome
        if not f.is_file():
            return []
        try:
            return list(json.loads(f.read_text("utf-8")).get(chave, []))
        except (ValueError, OSError):
            return []

    def _gravar(self, nome: str, chave: str, itens: list[dict[str, Any]]) -> None:
        (self.dir / nome).write_text(
            json.dumps({chave: itens}, ensure_ascii=False, indent=2), "utf-8"
        )

    # ---- projetos ----
    def projetos(self) -> list[dict[str, Any]]:
        return self._ler("projetos.json", "projetos")

    def criar_projeto(self, nome: str) -> dict[str, Any]:
        itens = self.projetos()
        proj = {"id": uuid4().hex[:8], "nome": nome, "criado_em": _agora(), "perguntas": []}
        itens.append(proj)
        self._gravar("projetos.json", "projetos", itens)
        return proj

    def projeto(self, pid: str) -> dict[str, Any] | None:
        return next((p for p in self.projetos() if p["id"] == pid), None)

    def excluir_projeto(self, pid: str) -> bool:
        itens = self.projetos()
        novos = [p for p in itens if p["id"] != pid]
        if len(novos) == len(itens):
            return False
        self._gravar("projetos.json", "projetos", novos)
        return True

    def adicionar_pergunta(self, pid: str, pergunta_id: str) -> dict[str, Any] | None:
        itens = self.projetos()
        proj = next((p for p in itens if p["id"] == pid), None)
        if proj is None:
            return None
        if pergunta_id not in proj["perguntas"]:
            proj["perguntas"].append(pergunta_id)
            self._gravar("projetos.json", "projetos", itens)
        return proj

    # ---- artefatos ----
    def artefatos(self) -> list[dict[str, Any]]:
        return self._ler("artefatos.json", "artefatos")

    def criar_artefato(self, pergunta_id: str, nome: str) -> dict[str, Any]:
        itens = self.artefatos()
        art = {
            "id": uuid4().hex[:8],
            "pergunta_id": pergunta_id,
            "nome": nome,
            "criado_em": _agora(),
        }
        itens.append(art)
        self._gravar("artefatos.json", "artefatos", itens)
        return art

    def excluir_artefato(self, aid: str) -> bool:
        itens = self.artefatos()
        novos = [a for a in itens if a["id"] != aid]
        if len(novos) == len(itens):
            return False
        self._gravar("artefatos.json", "artefatos", novos)
        return True
