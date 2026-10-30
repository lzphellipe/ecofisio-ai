"""Ferramentas que o agente pode chamar.

Princípio de rigor: o modelo nunca redige o trecho que cita. A busca devolve cada trecho com um
identificador curto (T1, T2, ...); na resposta final o modelo cita IDs, e a citação é montada a
partir do texto REAL do trecho guardado aqui. Assim não existe citação com trecho inventado.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ecofisio.evidence.models import Citation
from ecofisio.rag.index import LiteratureIndex, Passage

MAX_K = 10

SEARCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "buscar_literatura",
        "description": (
            "Busca trechos de artigos científicos abertos de biologia (qualquer área). "
            "Escreva a consulta em INGLÊS (o corpus é em inglês), com termos técnicos. "
            "Cada resultado traz um id (ex.: T3) para citar na resposta final."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "consulta": {"type": "string", "description": "consulta em inglês"},
                "k": {"type": "integer", "minimum": 1, "maximum": MAX_K, "default": 5},
            },
            "required": ["consulta"],
        },
    },
}


@dataclass(slots=True)
class PassageRegistry:
    """Trechos já mostrados ao modelo nesta conversa, por ID."""

    by_id: dict[str, Passage] = field(default_factory=dict)
    _by_chunk: dict[str, str] = field(default_factory=dict)

    def register(self, p: Passage) -> str:
        if p.chunk_id in self._by_chunk:
            return self._by_chunk[p.chunk_id]
        pid = f"T{len(self.by_id) + 1}"
        self.by_id[pid] = p
        self._by_chunk[p.chunk_id] = pid
        return pid

    def citation(self, pid: str) -> Citation:
        p = self.by_id[pid]  # KeyError = ID inexistente, tratado por quem chama
        if p.doi is None:
            raise ValueError(f"{pid}: trecho sem DOI")
        return Citation(doi=p.doi, passage=p.text, page=p.section)


class SearchTool:
    def __init__(self, index: LiteratureIndex, registry: PassageRegistry) -> None:
        self.index = index
        self.registry = registry

    def __call__(self, arguments: dict[str, Any]) -> str:
        """Executa a busca e devolve o JSON entregue ao modelo (erros também viram JSON)."""
        if "__invalid_json__" in arguments:
            return json.dumps({"erro": "argumentos não são JSON válido"}, ensure_ascii=False)
        query = str(arguments.get("consulta") or "").strip()
        if not query:
            return json.dumps({"erro": "consulta vazia"}, ensure_ascii=False)
        try:
            k = int(arguments.get("k", 5))
        except (TypeError, ValueError):
            k = 5
        k = max(1, min(k, MAX_K))
        hits = self.index.search(query, k=k, mode="hybrid" if self.index.embedder else "lexical")
        results = []
        for h in hits:
            r = h.as_tool_result()
            r.pop("score", None)
            r.pop("license", None)
            results.append({"id": self.registry.register(h.passage), **r})
        return json.dumps({"consulta": query, "resultados": results}, ensure_ascii=False)
