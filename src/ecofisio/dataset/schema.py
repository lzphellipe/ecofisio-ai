"""Formato dos exemplos de SFT (fine-tuning supervisionado).

Cada exemplo é uma conversa no padrão chat da OpenAI (`system`, `user`, `assistant`, `tool`),
exatamente a sequência que o agente produz: o modelo aprende a chamar `buscar_literatura`, ler os
trechos e responder no JSON auditado. Metadados (área, nível, tipo, DOIs citados) acompanham o
exemplo para medir cobertura e auditar a origem, mas NÃO vão para o texto de treino.

Licença: a destilação só deve usar um índice CC BY/CC0 (filtro na montagem do corpus), então todo
trecho citado já é liberado para treino. O campo `dois` deixa isso auditável.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

# tipos de exemplo, espelhando os tipos do benchmark mais a destilação factual
TIPOS = {"factual", "sem_resposta", "seguranca"}


@dataclass(slots=True)
class SFTExample:
    messages: list[dict[str, Any]]  # conversa completa no padrão chat
    tipo: str
    area: str = ""
    nivel: str = ""
    dois: list[str] = field(default_factory=list)  # DOIs citados (auditoria de licença)
    origem: str = ""  # "destilado" ou "manual"

    def __post_init__(self) -> None:
        if self.tipo not in TIPOS:
            raise ValueError(f"tipo {self.tipo!r} fora de {sorted(TIPOS)}")
        if not self.messages or self.messages[0].get("role") != "system":
            raise ValueError("exemplo precisa começar com a mensagem de system")
        if self.messages[-1].get("role") != "assistant":
            raise ValueError("exemplo precisa terminar com a resposta do assistant")

    @property
    def key(self) -> str:
        """Chave estável (hash do primeiro turno do usuário), para split determinístico."""
        user = next((m for m in self.messages if m.get("role") == "user"), None)
        base = (user or {}).get("content", "") or json.dumps(self.messages, ensure_ascii=False)
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    def to_jsonl_obj(self) -> dict[str, Any]:
        return {
            "messages": self.messages,
            "meta": {
                "tipo": self.tipo,
                "area": self.area,
                "nivel": self.nivel,
                "dois": self.dois,
                "origem": self.origem,
            },
        }


def dumps_jsonl(examples: list[SFTExample]) -> str:
    return "".join(json.dumps(e.to_jsonl_obj(), ensure_ascii=False) + "\n" for e in examples)
