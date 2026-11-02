"""Lê e valida o dataset de SFT (saída do ecofisio-dataset) para o treino.

Cada linha é {"messages": [...], "meta": {...}} no padrão chat. Para o treino importam só as
mensagens; os metadados servem para estatística. Validação defensiva: um exemplo malformado
derruba o treino cedo, com mensagem clara, em vez de corromper o ajuste em silêncio.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

PAPEIS = {"system", "user", "assistant", "tool"}


def carregar_sft(path: Path) -> list[dict[str, Any]]:
    """Devolve [{"messages": [...]}] validado. Erro claro se o arquivo não presta."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"dataset não encontrado: {p}")
    exemplos: list[dict[str, Any]] = []
    for n, linha in enumerate(p.read_text("utf-8").splitlines(), 1):
        if not linha.strip():
            continue
        try:
            obj = json.loads(linha)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{p.name}:{n}: JSON inválido ({exc.msg})") from exc
        msgs = obj.get("messages")
        if not isinstance(msgs, list) or not msgs:
            raise ValueError(f"{p.name}:{n}: 'messages' ausente ou vazio")
        if msgs[0].get("role") != "system":
            raise ValueError(f"{p.name}:{n}: a conversa precisa começar com 'system'")
        if msgs[-1].get("role") != "assistant":
            raise ValueError(f"{p.name}:{n}: a conversa precisa terminar com 'assistant'")
        for m in msgs:
            if m.get("role") not in PAPEIS:
                raise ValueError(f"{p.name}:{n}: papel inválido {m.get('role')!r}")
        exemplos.append({"messages": msgs})
    if not exemplos:
        raise ValueError(f"{p.name}: nenhum exemplo")
    return exemplos


def estatisticas(path: Path) -> dict[str, Any]:
    """Contagens por tipo/área/origem (do meta de cada linha), para o relatório antes do treino."""
    p = Path(path)
    tipo: Counter[str] = Counter()
    area: Counter[str] = Counter()
    origem: Counter[str] = Counter()
    n = 0
    for linha in p.read_text("utf-8").splitlines():
        if not linha.strip():
            continue
        meta = json.loads(linha).get("meta", {})
        n += 1
        tipo[meta.get("tipo") or "(sem)"] += 1
        area[meta.get("area") or "(sem)"] += 1
        origem[meta.get("origem") or "(sem)"] += 1
    return {
        "n": n,
        "por_tipo": dict(tipo.most_common()),
        "por_area": dict(area.most_common()),
        "por_origem": dict(origem.most_common()),
    }
