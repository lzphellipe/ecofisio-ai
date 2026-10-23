"""Verificação ao vivo da API do Europe PMC. Rode na sua máquina antes de um download grande:

    python scripts/smoke_europepmc.py --email seu-contato@exemplo.org

Confere três coisas que os testes (sem rede) não conseguem: as chaves reais do JSON de busca, se
o fullTextXML de um artigo aberto é JATS que o parser entende, e qual licença ele declara.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from ecofisio.literature import chunk_article, parse_jats
from ecofisio.literature.europepmc import EuropePMCClient


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", default=None, help="contato enviado à API (recomendado)")
    ap.add_argument("--query", default='"stomatal conductance" AND drought AND OPEN_ACCESS:y')
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        c = EuropePMCClient(Path(tmp), email=args.email)
        hits, cursor = c.search_page(args.query, page_size=5)
        print(f"{len(hits)} resultados na 1ª página; nextCursorMark={cursor!r}")
        if not hits:
            print("Nenhum resultado: confira a sintaxe da query no Europe PMC.")
            return
        print("chaves do 1º resultado:", sorted(hits[0].raw))
        for h in hits:
            print(f"- {h.pmcid} | doi={h.doi} | OA={h.is_open_access} | {h.title[:70]}")
        target = next((h for h in hits if h.pmcid), None)
        if target is None:
            print("Nenhum resultado com PMCID na 1ª página.")
            return
        xml = c.full_text_xml(target.pmcid)
        if xml is None:
            print(f"{target.pmcid}: sem fullTextXML")
            return
        art = parse_jats(xml)
        chunks = chunk_article(art)
        print(
            json.dumps(
                {
                    "pmcid": art.pmcid,
                    "doi": art.doi,
                    "license": art.license,
                    "license_source": art.license_source,
                    "training_allowed": art.license.training_allowed,
                    "paragraphs": len(art.paragraphs),
                    "chunks": len(chunks),
                    "first_sections": sorted({p.section for p in art.paragraphs})[:8],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        c.close()


if __name__ == "__main__":
    main()
