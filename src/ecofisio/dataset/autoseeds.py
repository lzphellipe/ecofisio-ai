"""Gera perguntas-semente a partir do próprio corpus (self-instruct ancorado).

Para cada trecho indexado, o modelo formula uma pergunta de pesquisa que o trecho responde.
Como a pergunta nasce de um trecho que ESTÁ no índice, a busca do agente tende a reencontrá-lo na
destilação — então quase nada cai no portão por falta de cobertura, e o dataset escala de verdade.

As perguntas geradas ainda passam pelo mesmo portão de qualidade na destilação: o modelo precisa
buscar, citar e ser auditado. A geração só garante que existe base no corpus para a pergunta.
"""

from __future__ import annotations

import random
import re

from ecofisio.agent.llm import ChatModel
from ecofisio.dataset.seeds import SeedQuestion
from ecofisio.rag.index import LiteratureIndex

PROMPT = (
    "Abaixo há um trecho de um artigo científico de biologia. Escreva UMA pergunta de pesquisa "
    "em português, clara e específica, que esse trecho ajuda a responder. A pergunta deve fazer "
    "sentido para quem conhece a literatura da área (não cite 'o trecho'). Responda apenas com a "
    "pergunta, sem aspas, sem numeração e sem explicação.\n\nTrecho:\n"
)

_MARCADOR = re.compile(r"^\s*(?:\d+[.)]\s*|[-*]\s*)")


def _limpar(texto: str) -> str:
    """Primeira linha, sem aspas/numeração; aceita só se parecer uma pergunta."""
    linha = next((ln.strip() for ln in (texto or "").splitlines() if ln.strip()), "")
    linha = _MARCADOR.sub("", linha).strip().strip("\"'").strip()
    return linha if ("?" in linha and len(linha) >= 12) else ""


def gerar_sementes(
    index: LiteratureIndex,
    model: ChatModel,
    n: int,
    *,
    so_primarios: bool = True,
    seed: int = 0,
    max_chars: int = 1500,
) -> list[SeedQuestion]:
    """Até `n` perguntas factuais derivadas de trechos do índice (embaralhados, deduplicadas)."""
    candidatos = [p for p in index.passages if (p.primary_evidence or not so_primarios)]
    random.Random(seed).shuffle(candidatos)
    sementes: list[SeedQuestion] = []
    vistos: set[str] = set()
    for p in candidatos:
        if len(sementes) >= n:
            break
        reply = model.chat([{"role": "user", "content": PROMPT + p.text[:max_chars]}])
        q = _limpar(reply.content)
        chave = q.lower()
        if q and chave not in vistos:
            vistos.add(chave)
            sementes.append(SeedQuestion(q, "factual", area="", nivel=""))
    return sementes
