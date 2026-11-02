"""Lentes de especialista: foco de domínio aplicado POR CIMA do contrato de rigor.

Cada lente especializa o foco e o vocabulário da resposta, mas NÃO substitui o system prompt do
agente — as regras de buscar, citar trechos reais, responder no JSON auditado, calibrar e recusar
uso duplo continuam valendo. Por isso aqui guardamos só o `foco` (um adendo), nunca um prompt
completo que diga "você é X e responda livremente".

As personas vieram dos agentes do projeto "Agente De IA Biologia". O "Engenheiro de Dados" ficou
de fora de propósito: ele é o módulo preditivo (fase 4), não um respondedor de literatura.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Especialista:
    id: str
    label: str
    foco: str  # adendo ao system prompt; vazio = sem especialização (geral)


ESPECIALISTAS: list[Especialista] = [
    Especialista("geral", "Geral (biologia)", ""),
    Especialista(
        "celular",
        "Biologia celular e genética",
        "Priorize mecanismos celulares e genéticos: divisão celular, organelas (cloroplastos, "
        "mitocôndrias), transcrição, tradução e sinalização intracelular. Enquadre a resposta "
        "nesse nível microscópico quando a pergunta permitir.",
    ),
    Especialista(
        "bioquimica",
        "Bioquímica vegetal",
        "Priorize rotas metabólicas e energia: fotossíntese (reações luminosas e ciclo de Calvin), "
        "vias C3/C4/CAM, respiração, metabólitos secundários (alcaloides, terpenos, fenóis) e "
        "fitormônios. Use terminologia química precisa.",
    ),
    Especialista(
        "ecofisiologia",
        "Ecofisiologia vegetal",
        "Priorize a interface planta-ambiente: relações hídricas (transpiração, potencial hídrico, "
        "fechamento estomático), estresse abiótico (seca, salinidade, temperatura, UV), "
        "aclimatação e fenologia.",
    ),
]

_POR_ID = {e.id: e for e in ESPECIALISTAS}


def especialistas() -> list[Especialista]:
    return ESPECIALISTAS


def foco_de(especialista_id: str | None) -> str:
    """Texto de foco da lente (ou vazio se desconhecida/geral)."""
    e = _POR_ID.get(especialista_id or "geral")
    return e.foco if e else ""
