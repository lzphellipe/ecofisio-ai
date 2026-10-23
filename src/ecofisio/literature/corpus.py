"""Monta o corpus de literatura: busca no Europe PMC → baixa JATS → lê licença → indexa.

Cada artigo encontrado gera uma linha no relatório (`corpus_report.jsonl`) dizendo se entrou e,
se não, por quê. Nada é descartado em silêncio.

Uso:
    python -m ecofisio.literature.corpus \\
        --query '"stomatal conductance" AND drought AND OPEN_ACCESS:y' \\
        --max 200 --email contato@exemplo.org --out data/processed/literature

Confira a sintaxe da query no Europe PMC (scripts/smoke_europepmc.py) antes de um download grande.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from ecofisio.literature.europepmc import EuropePMCClient
from ecofisio.literature.jats import License, parse_jats
from ecofisio.rag.index import LiteratureIndex


@dataclass(slots=True)
class CorpusEntry:
    pmcid: str | None
    doi: str | None
    title: str
    status: str  # "indexado" ou o motivo da exclusão
    license: str | None = None
    passages: int = 0
    training_allowed: bool = False


def build_corpus(
    client: EuropePMCClient,
    query: str,
    index: LiteratureIndex,
    *,
    max_articles: int = 100,
    allowed_licenses: set[License] | None = None,
) -> list[CorpusEntry]:
    """Preenche `index` e devolve uma entrada por artigo encontrado na busca."""
    report: list[CorpusEntry] = []
    for hit in client.search(query, max_results=max_articles):
        entry = CorpusEntry(pmcid=hit.pmcid, doi=hit.doi, title=hit.title, status="")
        report.append(entry)
        if not hit.pmcid:
            entry.status = "sem PMCID (sem texto completo no PMC)"
            continue
        try:
            xml = client.full_text_xml(hit.pmcid)
        except Exception as exc:  # noqa: BLE001 - qualquer falha de rede vira motivo registrado
            entry.status = f"erro ao baixar: {exc}"
            continue
        if xml is None:
            entry.status = "sem fullTextXML"
            continue
        try:
            article = parse_jats(xml)
        except Exception as exc:  # noqa: BLE001 - XML ruim não derruba o lote
            entry.status = f"XML inválido: {exc}"
            continue
        entry.doi = article.doi or entry.doi
        entry.license = str(article.license)
        entry.training_allowed = article.license.training_allowed
        if allowed_licenses is not None and article.license not in allowed_licenses:
            entry.status = f"licença fora do filtro ({article.license})"
            continue
        if not article.citable:
            entry.status = "sem DOI no artigo (não citável)"
            continue
        if not article.paragraphs:
            entry.status = "sem texto extraível"
            continue
        n = index.add_article(article)
        entry.passages = n
        entry.status = "indexado" if n else "duplicado"
    return report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--query", required=True)
    ap.add_argument("--max", type=int, default=100, dest="max_articles")
    ap.add_argument("--email", default=None)
    ap.add_argument("--out", type=Path, default=Path("data/processed/literature"))
    ap.add_argument("--raw", type=Path, default=Path("data/raw/europepmc"))
    ap.add_argument(
        "--licenses",
        default=None,
        help="ex.: CC-BY,CC0 (padrão: todas; a licença fica registrada em cada trecho)",
    )
    ap.add_argument("--embedder", default=None, help="modelo sentence-transformers (opcional)")
    ap.add_argument("--query-prefix", default="")
    ap.add_argument("--passage-prefix", default="")
    args = ap.parse_args(argv)

    embedder = None
    if args.embedder:
        from ecofisio.rag.embed import SentenceTransformerEmbedder

        embedder = SentenceTransformerEmbedder(
            args.embedder, query_prefix=args.query_prefix, passage_prefix=args.passage_prefix
        )
    allowed = {License(x.strip()) for x in args.licenses.split(",")} if args.licenses else None

    client = EuropePMCClient(args.raw, email=args.email)
    index = LiteratureIndex(embedder)
    report = build_corpus(
        client, args.query, index, max_articles=args.max_articles, allowed_licenses=allowed
    )
    client.close()
    index.save(args.out)
    with (args.out / "corpus_report.jsonl").open("w", encoding="utf-8") as f:
        for e in report:
            f.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")
    (args.out / "query.json").write_text(
        json.dumps({"query": args.query, "max": args.max_articles, "licenses": args.licenses}),
        "utf-8",
    )

    counts = Counter(
        "indexado" if e.status == "indexado" else e.status.split(" (")[0] for e in report
    )
    print(f"{len(report)} artigos encontrados, {len(index)} trechos indexados em {args.out}")
    for status, n in counts.most_common():
        print(f"  {n:4d}  {status}")


if __name__ == "__main__":
    main()
