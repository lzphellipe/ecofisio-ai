"""Métricas por pergunta, calculadas a partir da resposta do agente.

Os motivos de bloqueio são classificados pelo texto que o próprio código do agente e da auditoria
produz; `tests/test_eval.py` gera cada motivo pelo caminho real, então uma mudança de mensagem
quebra o teste em vez de virar "outro" em silêncio.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from ecofisio.agent.research import ResearchAnswer
from ecofisio.eval.benchmark import BenchmarkItem
from ecofisio.evidence.models import EvidenceStrength

# (categoria, trecho que identifica a mensagem), em ordem de verificação
_REASON_PATTERNS: list[tuple[str, str]] = [
    ("citacao_inventada", "trecho inexistente"),
    ("forca_invalida", "força da evidência inválida"),
    ("status_invalido", "status inválido"),
    ("consenso_insuficiente", "consenso exige"),
    ("sem_citacao", "exige ao menos uma citação"),
    ("sem_doi", "trecho sem doi"),
    ("retratado", "artigo retratado"),
    ("retratacao_nao_verificada", "retratação não verificada"),
    ("semantica_nao_verificada", "sustentação semântica não verificada"),
    ("trecho_nao_sustenta", "não sustenta"),
    ("trecho_contradiz", "contradiz"),
]
STRONG = {EvidenceStrength.CONSENSO, EvidenceStrength.RESULTADO_ISOLADO}


def classify_reason(reason: str) -> str:
    low = reason.lower()
    for category, needle in _REASON_PATTERNS:
        if needle in low:
            return category
    return "outro"


@dataclass(slots=True)
class QuestionResult:
    id: str
    tipo: str
    avaliacao: str
    ok: bool
    erro: str | None = None
    latencia_s: float = 0.0
    passos: int = 0
    reparos: int = 0
    tokens: int = 0
    buscas: int = 0
    entregues: int = 0
    entregues_fortes: int = 0  # consenso ou resultado isolado
    bloqueadas: int = 0
    lacunas: int = 0
    motivos: dict[str, int] = field(default_factory=dict)
    dois_citados: list[str] = field(default_factory=list)
    dois_esperados: list[str] = field(default_factory=list)
    dois_esperados_fora_do_indice: list[str] = field(default_factory=list)

    @property
    def recall_dois(self) -> float | None:
        """Fração dos DOIs esperados citados em afirmações entregues (None se não há esperados
        dentro do índice: não dá para cobrar o que o modelo não tinha como achar)."""
        alcancaveis = set(self.dois_esperados) - set(self.dois_esperados_fora_do_indice)
        if not alcancaveis:
            return None
        return len(alcancaveis & set(self.dois_citados)) / len(alcancaveis)

    @property
    def absteve_corretamente(self) -> bool | None:
        """Pergunta fora do escopo: nenhuma afirmação forte entregue e lacuna registrada."""
        if self.tipo != "sem_resposta" or not self.ok:
            return None
        return self.entregues_fortes == 0 and self.lacunas > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "recall_dois": self.recall_dois,
            "absteve_corretamente": self.absteve_corretamente,
        }


def score(
    item: BenchmarkItem,
    answer: ResearchAnswer | None,
    *,
    latency_s: float,
    indexed_dois: set[str],
    error: str | None = None,
) -> QuestionResult:
    fora = sorted(set(item.dois_esperados) - indexed_dois)
    res = QuestionResult(
        id=item.id,
        tipo=item.tipo,
        avaliacao=item.avaliacao,
        ok=answer is not None,
        erro=error,
        latencia_s=round(latency_s, 3),
        dois_esperados=list(item.dois_esperados),
        dois_esperados_fora_do_indice=fora,
    )
    if answer is None:
        return res
    motivos: Counter[str] = Counter()
    for b in answer.blocked:
        for r in b.reasons:
            motivos[classify_reason(r)] += 1
    res.passos, res.reparos = answer.steps, answer.repairs
    res.tokens = int(answer.usage.get("total_tokens", 0))
    res.buscas = len(answer.searches)
    res.entregues = len(answer.delivered)
    res.entregues_fortes = sum(r.claim.strength in STRONG for r in answer.delivered)
    res.bloqueadas = len(answer.blocked)
    res.lacunas = len(answer.gaps)
    res.motivos = dict(motivos)
    res.dois_citados = sorted({c.doi for r in answer.delivered for c in r.claim.citations})
    return res
