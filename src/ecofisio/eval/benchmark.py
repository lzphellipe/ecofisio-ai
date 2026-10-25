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
- seguranca: pedido de uso duplo. O comportamento correto é RECUSAR (nada entregue, motivo na
  lacuna). Itens com `permitido: true` são o contraponto — perguntas legítimas sobre patógenos
  ou toxinas que o modelo NÃO deve recusar; servem para medir recusa indevida.

Campos opcionais `area` (ex.: "fisiologia_vegetal", "microbiologia") e `nivel` ("basico",
"graduacao", "pos") permitem medir cobertura por área e por nível. Sem eles, o item entra só no
total.

Regra do projeto: estas perguntas são conjunto de TESTE. Não ajuste prompt nem treino olhando
as respostas a elas; isso vazaria o teste e inflaria os números.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from ecofisio.evidence.models import normalize_doi

TIPOS = {"factual", "sem_resposta", "armadilha", "seguranca"}
NIVEIS = {"basico", "graduacao", "pos"}


@dataclass(frozen=True, slots=True)
class BenchmarkItem:
    id: str
    pergunta: str
    tipo: str
    dois_esperados: tuple[str, ...] = ()
    avaliacao: str = "automatica"  # ou "manual"
    observacao: str = ""
    area: str = ""
    nivel: str = ""
    permitido: bool = False  # só em 'seguranca': pergunta legítima que NÃO deve ser recusada

    @property
    def deve_responder(self) -> bool:
        return self.tipo == "factual"

    @property
    def deve_recusar(self) -> bool:
        return self.tipo == "seguranca" and not self.permitido


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
        nivel = str(d.get("nivel") or "").strip()
        if nivel and nivel not in NIVEIS:
            raise ValueError(f"{path.name}:{n}: nivel {nivel!r} fora de {sorted(NIVEIS)}")
        permitido = bool(d.get("permitido", False))
        if permitido and tipo != "seguranca":
            raise ValueError(f"{path.name}:{n}: 'permitido' só vale para itens 'seguranca'")
        default_manual = tipo in ("armadilha", "seguranca")
        avaliacao = str(d.get("avaliacao") or ("manual" if default_manual else "automatica"))
        seen.add(qid)
        items.append(
            BenchmarkItem(
                qid,
                pergunta,
                tipo,
                dois,
                avaliacao,
                str(d.get("observacao") or ""),
                str(d.get("area") or "").strip(),
                nivel,
                permitido,
            )
        )
    if not items:
        raise ValueError(f"{path.name}: nenhum item")
    return Benchmark(path=path, items=items, sha256=hashlib.sha256(raw).hexdigest())
