"""Agregação das métricas, intervalos por bootstrap e comparação entre execuções.

Incerteza: IC 95% por bootstrap de percentil, reamostrando PERGUNTAS (a unidade independente),
2000 réplicas, semente fixa. Com poucas perguntas (o conjunto semente tem 13) os intervalos ficam
largos, e é isso que deve aparecer: diferença dentro do intervalo não é diferença.

Comparação A vs B: bootstrap PAREADO sobre as perguntas presentes nas duas execuções, que é mais
sensível que comparar dois intervalos independentes.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

Row = dict[str, Any]
N_BOOT = 2000
SEED = 0


def _mean(vals: list[float]) -> float | None:
    return float(np.mean(vals)) if vals else None


def _ok(rows: Sequence[Row]) -> list[Row]:
    return [r for r in rows if r["ok"]]


def _blocked_share(rows: Sequence[Row]) -> float | None:
    ok = _ok(rows)
    total = sum(r["entregues"] + r["bloqueadas"] for r in ok)
    return sum(r["bloqueadas"] for r in ok) / total if total else None


def _invented_per_q(rows: Sequence[Row]) -> float | None:
    ok = _ok(rows)
    return _mean([r["motivos"].get("citacao_inventada", 0) for r in ok])


@dataclass(frozen=True, slots=True)
class Metric:
    key: str
    label: str
    fn: Callable[[Sequence[Row]], float | None]
    better: str  # "maior" | "menor" | "" (só descritiva)
    pct: bool = False


METRICS: list[Metric] = [
    Metric(
        "taxa_erro",
        "Perguntas com erro (modelo/JSON)",
        lambda rs: _mean([0.0 if r["ok"] else 1.0 for r in rs]),
        "menor",
        True,
    ),
    Metric(
        "taxa_busca",
        "Perguntas com ao menos uma busca",
        lambda rs: _mean([1.0 if r["buscas"] > 0 else 0.0 for r in _ok(rs)]),
        "maior",
        True,
    ),
    Metric("fracao_bloqueada", "Afirmações bloqueadas / total", _blocked_share, "menor", True),
    Metric("inventadas_por_pergunta", "Citações inventadas por pergunta", _invented_per_q, "menor"),
    Metric(
        "respondeu_factual",
        "Factuais com ao menos uma afirmação entregue",
        lambda rs: _mean(
            [1.0 if r["entregues"] > 0 else 0.0 for r in _ok(rs) if r["tipo"] == "factual"]
        ),
        "maior",
        True,
    ),
    Metric(
        "recall_dois",
        "DOIs esperados citados (recall)",
        lambda rs: _mean([r["recall_dois"] for r in _ok(rs) if r["recall_dois"] is not None]),
        "maior",
        True,
    ),
    Metric(
        "abstencao_correta",
        "Fora do escopo: absteve-se corretamente",
        lambda rs: _mean(
            [
                1.0 if r["absteve_corretamente"] else 0.0
                for r in _ok(rs)
                if r["absteve_corretamente"] is not None
            ]
        ),
        "maior",
        True,
    ),
    Metric(
        "buscas_por_pergunta",
        "Buscas por pergunta",
        lambda rs: _mean([r["buscas"] for r in _ok(rs)]),
        "",
    ),
    Metric(
        "latencia_s",
        "Latência por pergunta (s)",
        lambda rs: _mean([r["latencia_s"] for r in _ok(rs)]),
        "menor",
    ),
    Metric(
        "tokens",
        "Tokens por pergunta",
        lambda rs: _mean([r["tokens"] for r in _ok(rs) if r["tokens"]]),
        "",
    ),
]


def bootstrap_ci(
    rows: Sequence[Row], fn: Callable[[Sequence[Row]], float | None]
) -> tuple[float | None, float | None]:
    if len(rows) < 2:
        return None, None
    rng = np.random.default_rng(SEED)
    vals = []
    for _ in range(N_BOOT):
        sample = [rows[i] for i in rng.integers(0, len(rows), len(rows))]
        v = fn(sample)
        if v is not None:
            vals.append(v)
    if len(vals) < N_BOOT // 2:  # métrica indefinida na maioria das réplicas
        return None, None
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def summarize(rows: Sequence[Row]) -> dict[str, Any]:
    out: dict[str, Any] = {"n_perguntas": len(rows), "metricas": {}}
    for m in METRICS:
        lo, hi = bootstrap_ci(rows, m.fn)
        out["metricas"][m.key] = {"valor": m.fn(rows), "ic95": [lo, hi]}
    motivos: Counter[str] = Counter()
    for r in rows:
        motivos.update(r["motivos"])
    out["motivos_bloqueio"] = dict(motivos.most_common())
    out["dois_esperados_fora_do_indice"] = sorted(
        {d for r in rows for d in r["dois_esperados_fora_do_indice"]}
    )
    return out


def _fmt(v: float | None, pct: bool) -> str:
    if v is None:
        return "—"
    return f"{100 * v:.0f}%" if pct else f"{v:.2f}"


def render_markdown(meta: dict[str, Any], rows: Sequence[Row], summary: dict[str, Any]) -> str:
    lines = [
        f"# Avaliação: {meta.get('rotulo') or meta['modelo']}",
        "",
        f"Modelo `{meta['modelo']}` · benchmark `{meta['benchmark']}` "
        f"({summary['n_perguntas']} perguntas) · {meta['criado_em']}",
        "",
        "| Métrica | Valor | IC 95% |",
        "| --- | --- | --- |",
    ]
    for m in METRICS:
        d = summary["metricas"][m.key]
        lo, hi = d["ic95"]
        ic = "—" if lo is None else f"{_fmt(lo, m.pct)} a {_fmt(hi, m.pct)}"
        lines.append(f"| {m.label} | {_fmt(d['valor'], m.pct)} | {ic} |")
    if summary["motivos_bloqueio"]:
        lines += ["", "Motivos de bloqueio:", ""]
        lines += [f"- {k}: {v}" for k, v in summary["motivos_bloqueio"].items()]
    if summary["dois_esperados_fora_do_indice"]:
        lines += ["", "DOIs esperados que não estão no índice (fora do cálculo de recall):", ""]
        lines += [f"- {d}" for d in summary["dois_esperados_fora_do_indice"]]
    manual = [r["id"] for r in rows if r["avaliacao"] == "manual"]
    if manual:
        lines += ["", f"Revisão humana pendente (armadilhas): {', '.join(manual)}"]
    lines += [
        "",
        "| Pergunta | Tipo | Entregues | Bloqueadas | Buscas | Latência (s) | Erro |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['tipo']} | {r['entregues']} | {r['bloqueadas']} | {r['buscas']} "
            f"| {r['latencia_s']:.1f} | {r['erro'] or ''} |"
        )
    return "\n".join(lines) + "\n"


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Diferença B − A por métrica, com IC 95% por bootstrap pareado nas perguntas comuns."""
    if a["meta"]["benchmark_sha256"] != b["meta"]["benchmark_sha256"]:
        raise ValueError("as execuções usaram versões diferentes do benchmark: não são comparáveis")
    ra = {r["id"]: r for r in a["perguntas"]}
    rb = {r["id"]: r for r in b["perguntas"]}
    ids = sorted(set(ra) & set(rb))
    rng = np.random.default_rng(SEED)
    boots = [rng.integers(0, len(ids), len(ids)) for _ in range(N_BOOT)] if len(ids) > 1 else []
    out: dict[str, Any] = {"perguntas_comuns": len(ids), "metricas": {}}
    for m in METRICS:
        va, vb = m.fn([ra[i] for i in ids]), m.fn([rb[i] for i in ids])
        diffs = []
        for idx in boots:
            sa = m.fn([ra[ids[j]] for j in idx])
            sb = m.fn([rb[ids[j]] for j in idx])
            if sa is not None and sb is not None:
                diffs.append(sb - sa)
        ic = (
            [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))]
            if len(diffs) >= max(1, len(boots) // 2)
            else [None, None]
        )
        diff = None if va is None or vb is None else vb - va
        if ic[0] is None or diff is None:
            veredito = "indefinido"
        elif ic[0] <= 0 <= ic[1]:
            veredito = "sem diferença detectável"
        elif not m.better:
            veredito = "diferente"
        else:
            melhorou = (diff > 0) == (m.better == "maior")
            veredito = "B melhor" if melhorou else "B pior"
        out["metricas"][m.key] = {
            "A": va,
            "B": vb,
            "diferenca": diff,
            "ic95": ic,
            "veredito": veredito,
        }
    return out


def render_comparison(a: dict[str, Any], b: dict[str, Any], cmp: dict[str, Any]) -> str:
    la = a["meta"].get("rotulo") or a["meta"]["modelo"]
    lb = b["meta"].get("rotulo") or b["meta"]["modelo"]
    lines = [
        f"A = {la} · B = {lb} · {cmp['perguntas_comuns']} perguntas comuns",
        "",
        "| Métrica | A | B | B − A | IC 95% (pareado) | Veredito |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for m in METRICS:
        d = cmp["metricas"][m.key]
        lo, hi = d["ic95"]
        ic = "—" if lo is None else f"{_fmt(lo, m.pct)} a {_fmt(hi, m.pct)}"
        lines.append(
            f"| {m.label} | {_fmt(d['A'], m.pct)} | {_fmt(d['B'], m.pct)} "
            f"| {_fmt(d['diferenca'], m.pct)} | {ic} | {d['veredito']} |"
        )
    return "\n".join(lines) + "\n"
