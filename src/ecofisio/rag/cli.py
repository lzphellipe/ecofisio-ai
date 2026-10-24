"""Busca direta no corpus de literatura, sem LLM.

    ecofisio-busca "stomatal conductance drought recovery"
    ecofisio-busca "Fv/Fm water deficit" -k 10 --so-primarios
    ecofisio-busca "abscisic acid stomatal closure" --json > resultado.json

O corpus é em inglês: consultas em inglês, com termos técnicos, rendem muito mais. A busca é
lexical (BM25); cada resultado traz DOI, ano, seção e tipo de publicação, prontos para citar.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

from ecofisio.rag.index import LiteratureIndex


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("consulta", nargs="+", help="termos da busca (em inglês)")
    ap.add_argument("-k", type=int, default=5, help="quantos trechos mostrar (padrão 5)")
    ap.add_argument("--index", type=Path, default=Path("data/processed/literature"))
    ap.add_argument(
        "--so-primarios",
        action="store_true",
        help="só artigos de pesquisa original (exclui editoriais, revisões, comentários)",
    )
    ap.add_argument("--trecho", type=int, default=400, help="caracteres do trecho (0 = inteiro)")
    ap.add_argument("--json", action="store_true", help="saída em JSON")
    args = ap.parse_args(argv)

    if args.k < 1:
        ap.error("-k precisa ser 1 ou mais")
    if not (args.index / "meta.json").exists():
        ap.error(f"índice não encontrado em {args.index}: rode o ecofisio-corpus antes")
    query = " ".join(args.consulta)
    index = LiteratureIndex.load(args.index)
    # busca mais candidatos quando há filtro, para ainda sobrarem k depois dele
    hits = index.search(query, k=args.k * 5 if args.so_primarios else args.k, mode="lexical")
    if args.so_primarios:
        hits = [h for h in hits if h.passage.primary_evidence][: args.k]

    if args.json:
        out = [{"posicao": i, **h.as_tool_result()} for i, h in enumerate(hits, 1)]
        json.dump({"consulta": query, "resultados": out}, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    if not hits:
        print(f'Nenhum trecho encontrado para "{query}". Tente termos em inglês ou mais gerais.')
        return 0
    print(f'{len(hits)} trechos para "{query}" ({len(index)} trechos no índice)\n')
    for i, h in enumerate(hits, 1):
        p = h.passage
        tipo = p.article_type or "tipo desconhecido"
        aviso = "" if p.primary_evidence else "  [não é pesquisa primária]"
        print(f"{i}. {p.title} ({p.year or 's/ ano'})")
        print(f"   doi:{p.doi} · {p.section} · {tipo}{aviso}")
        text = (
            p.text
            if args.trecho == 0
            else textwrap.shorten(p.text, args.trecho, placeholder=" […]")
        )
        print(textwrap.indent(textwrap.fill(text, 96), "   "))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
