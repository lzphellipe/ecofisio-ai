"""Transforma a resposta do agente (modelo base + RAG) em exemplo de SFT, com portão de qualidade.

Destilação: o modelo base responde às sementes usando a busca; só as respostas que passam no
portão viram alvo de treino. O portão é o próprio rigor do projeto — o modelo ajustado deve
aprender só comportamento verificável:

- factual: pelo menos uma afirmação ENTREGUE (passou na auditoria), nenhuma BLOQUEADA, nenhuma
  citação inventada, ao menos uma busca, e zero reparos de JSON. Se alguma afirmação foi
  bloqueada, a conversa inteira é descartada — não se ensina a errar e corrigir.
- sem_resposta: nenhuma afirmação forte entregue e ao menos uma lacuna (calibração: "não sei").

Quando passa, a transcrição já está limpa (o JSON final do modelo só contém o que foi auditado),
então ela é usada como está, sem reescrever o alvo.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ecofisio.agent.research import ResearchAnswer
from ecofisio.dataset.schema import SFTExample
from ecofisio.dataset.seeds import SeedQuestion
from ecofisio.evidence.models import EvidenceStrength

STRONG = {EvidenceStrength.CONSENSO, EvidenceStrength.RESULTADO_ISOLADO}


def _passes_gate(answer: ResearchAnswer, tipo: str) -> bool:
    if answer.repairs or answer.blocked:
        return False
    msgs = answer.transcript
    if not msgs or msgs[0].get("role") != "system" or msgs[-1].get("role") != "assistant":
        return False
    if tipo == "factual":
        return bool(answer.delivered) and len(answer.searches) > 0
    if tipo == "sem_resposta":
        fortes = sum(r.claim.strength in STRONG for r in answer.delivered)
        return fortes == 0 and len(answer.gaps) > 0
    return False


def example_from_answer(answer: ResearchAnswer, seed: SeedQuestion) -> SFTExample | None:
    """Exemplo de SFT se a resposta passar no portão; senão None (descartada)."""
    if not _passes_gate(answer, seed.tipo):
        return None
    dois = sorted({c.doi for r in answer.delivered for c in r.claim.citations})
    return SFTExample(
        messages=answer.transcript,
        tipo=seed.tipo,
        area=seed.area,
        nivel=seed.nivel,
        dois=dois,
        origem="destilado",
    )


def split_train_val(
    examples: list[SFTExample], val_pct: int = 15
) -> tuple[list[SFTExample], list[SFTExample]]:
    """Divide em treino/validação de forma determinística (hash da pergunta), sem aleatoriedade.

    O corte é por `key` (pergunta): o mesmo exemplo cai sempre no mesmo lado, e exemplos com a
    mesma pergunta nunca se dividem entre treino e validação (evita vazamento por duplicata).
    """
    if not 0 <= val_pct <= 100:
        raise ValueError("val_pct precisa estar entre 0 e 100")
    train, val = [], []
    for e in examples:
        bucket = int(e.key[:8], 16) % 100
        (val if bucket < val_pct else train).append(e)
    return train, val


def manifest(examples: list[SFTExample]) -> dict[str, Any]:
    """Resumo auditável do dataset: contagens por tipo, área, nível e origem, mais DOIs citados."""

    def counts(attr: str) -> dict[str, int]:
        c = Counter(getattr(e, attr) or "(vazio)" for e in examples)
        return dict(c.most_common())

    return {
        "n_exemplos": len(examples),
        "por_tipo": counts("tipo"),
        "por_area": counts("area"),
        "por_nivel": counts("nivel"),
        "por_origem": counts("origem"),
        "dois_citados": sorted({d for e in examples for d in e.dois}),
    }
