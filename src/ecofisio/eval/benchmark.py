"""Conjunto de perguntas do benchmark (JSONL versionado em `benchmarks/`).

Cada linha é um item:
    {"id": "q01", "pergunta": "...", "tipo": "factual",
     "dois_esperados": ["10.3390/..."], "observacao": "..."}

Tipos:
- factual: a literatura do corpus deveria responder. Mede-se busca, entrega e, se houver
  `dois_esperados`, quais artigos esperados foram citados.
- sem_resposta: fora do escopo do corpus. O comportamento correto é NÃO entregar afirmações
  com força de evidência (consenso/resultado isolado) e registrar a lacuna. Mede calibração.
- armadilha: premissa falsa ou valor impossível na pergunta. Correção julgada por humano
  (`avaliacao: manual`); as métricas automáticas só registram o comportamento.

Regra do projeto: estas perguntas são conjunto de TESTE. Não ajuste prompt nem treino olhando
as respostas a elas; isso vazaria o teste e inflaria os números.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from ecofisio.evidence.models import normalize_doi

TIPOS = {"factual", "sem_resposta", "armadilha"}


@dataclass(frozen=True, slots=True)
class BenchmarkItem:
    id: str
    pergunta: str
    tipo: str
    dois_esperados: tuple[str, ...] = ()
    avaliacao: str = "automatica"  # ou "manual"
    observacao: str = ""

    @property
    def deve_responder(self) -> bool:
        return self.tipo == "factual"


@dataclass(slots=True)
class Benchmark:
    path: Path
    items: list[BenchmarkItem] = field(default_factory=list)
    sha256: str = ""

    def __len__(self) -> int:
        return len(self.items)


def load_benchmark(path: Path) -> Benchmark:
    raw = path.read_bytes()
    items: list[BenchmarkItem] = []
    seen: set[str] = set()
    for n, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{n}: JSON inválido ({exc.msg})") from exc
        qid = str(d.get("id") or "").strip()
        pergunta = str(d.get("pergunta") or "").strip()
        tipo = str(d.get("tipo") or "").strip()
        if not qid or not pergunta:
            raise ValueError(f"{path.name}:{n}: 'id' e 'pergunta' são obrigatórios")
        if qid in seen:
            raise ValueError(f"{path.name}:{n}: id repetido {qid!r}")
        if tipo not in TIPOS:
            raise ValueError(f"{path.name}:{n}: tipo {tipo!r} fora de {sorted(TIPOS)}")
        dois = tuple(normalize_doi(x) for x in d.get("dois_esperados") or [])
        if dois and tipo != "factual":
            raise ValueError(f"{path.name}:{n}: só itens 'factual' têm dois_esperados")
        avaliacao = str(d.get("avaliacao") or ("manual" if tipo == "armadilha" else "automatica"))
        seen.add(qid)
        items.append(
            BenchmarkItem(qid, pergunta, tipo, dois, avaliacao, str(d.get("observacao") or ""))
        )
    if not items:
        raise ValueError(f"{path.name}: nenhum item")
    return Benchmark(path=path, items=items, sha256=hashlib.sha256(raw).hexdigest())
