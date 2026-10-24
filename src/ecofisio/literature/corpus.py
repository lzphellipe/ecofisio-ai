"""Monta o corpus de literatura: busca no Europe PMC → baixa JATS → lê licença → indexa.

Cada artigo encontrado gera uma linha no relatório (`corpus_report.jsonl`) dizendo se entrou e,
se não, por quê. Nada é descartado em silêncio.

Uso (a query num arquivo evita problemas de aspas no PowerShell e fica versionada):
    ecofisio-corpus --query-file queries/seca_trocas_gasosas.txt \\
        --query-file queries/baunilha.txt --max 200 \\
        --licenses CC-BY,CC0 --email contato@exemplo.org

O índice é refeito a cada execução com TODAS as queries passadas: para acrescentar um tema,
passe também os arquivos dos temas anteriores (o que já foi baixado vem do cache).

Confira a sintaxe da query no Europe PMC (scripts/smoke_europepmc.py) antes de um download grande.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

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
    consulta: str = ""  # nome da query (arquivo) que trouxe o artigo


def build_corpus(
    client: EuropePMCClient,
    query: str,
    index: LiteratureIndex,
    *,
    max_articles: int = 100,
    allowed_licenses: set[License] | None = None,
    label: str = "",
) -> list[CorpusEntry]:
    """Preenche `index` e devolve uma entrada por artigo encontrado na busca.

    Pode ser chamada várias vezes sobre o mesmo índice (uma por tema): artigos já indexados
    por uma query anterior voltam como "duplicado".
    """
    report: list[CorpusEntry] = []
    for hit in client.search(query, max_results=max_articles):
        entry = CorpusEntry(
            pmcid=hit.pmcid, doi=hit.doi, title=hit.title, status="", consulta=label
        )
        report.append(entry)
        if not hit.pmcid:
            entry.status = "sem PMCID (sem texto completo no PMC)"
            continue
        try:
            xml = client.full_text_xml(hit.pmcid)
        except Exception as exc:  # noqa: BLE001 - qualquer falha de rede vira motivo registrado
            entry.status = f"erro ao baixar ({_describe(exc)})"
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


def _describe(exc: Exception) -> str:
    """Erro curto, sem URL: a URL repetiria o e-mail de contato em cada linha do relatório."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


def read_query_file(path: Path) -> str:
    """Lê a query de um arquivo: ignora linhas vazias e comentários (#), junta o resto."""
    lines = path.read_text(encoding="utf-8-sig").splitlines()  # -sig: tolera BOM do Bloco de Notas
    query = " ".join(ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#"))
    if not query:
        raise SystemExit(f"{path}: arquivo de query vazio")
    return query


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--query", help="query do Europe PMC")
    src.add_argument(
        "--query-file",
        type=Path,
        action="append",
        help="arquivo com a query (# = comentário); repita para juntar temas no mesmo índice",
    )
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
    if args.query_file:
        queries = [(f.stem, read_query_file(f)) for f in args.query_file]
    else:
        queries = [("query", args.query)]

    embedder = None
    if args.embedder:
        from ecofisio.rag.embed import SentenceTransformerEmbedder

        embedder = SentenceTransformerEmbedder(
            args.embedder, query_prefix=args.query_prefix, passage_prefix=args.passage_prefix
        )
    allowed = {License(x.strip()) for x in args.licenses.split(",")} if args.licenses else None

    client = EuropePMCClient(args.raw, email=args.email)
    index = LiteratureIndex(embedder)
    report: list[CorpusEntry] = []
    for label, query in queries:
        report += build_corpus(
            client,
            query,
            index,
            max_articles=args.max_articles,
            allowed_licenses=allowed,
            label=label,
        )
    client.close()
    index.save(args.out)
    with (args.out / "corpus_report.jsonl").open("w", encoding="utf-8") as f:
        for e in report:
            f.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")
    (args.out / "query.json").write_text(
        json.dumps(
            {
                "queries": [{"nome": n, "query": q} for n, q in queries],
                "max_por_query": args.max_articles,
                "licenses": args.licenses,
            },
            ensure_ascii=False,
        ),
        "utf-8",
    )

    print(f"{len(report)} artigos encontrados, {len(index)} trechos indexados em {args.out}")
    for label, _ in queries:
        counts = Counter(e.status for e in report if e.consulta == label)
        if len(queries) > 1:
            print(f"{label}:")
        for status, n in counts.most_common():
            print(f"  {n:4d}  {status}")
    if any(e.status.startswith("erro ao baixar") for e in report):
        print(
            "Rode o mesmo comando de novo para tentar só os que falharam (os demais vêm do cache)."
        )


if __name__ == "__main__":
    main()
