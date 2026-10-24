"""Leitura de artigos no formato JATS (o XML do PubMed Central / Europe PMC).

O XML vem da internet, então é lido com `defusedxml` (bloqueia entidades externas e expansão
de entidades). A licença é lida do próprio artigo (`<license>` / `<ali:license_ref>`), não de
metadados de busca: é o que vale juridicamente para decidir se o texto pode entrar no treino.

JATS não tem número de página por parágrafo; o localizador de cada trecho é o caminho de seções
("Results > Gas exchange"), que vai no campo `page` da citação.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import fromstring

from ecofisio.evidence.models import normalize_doi

_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
_WS = re.compile(r"\s+")
_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")
# Elementos que não são texto corrido: tabelas e figuras entram em fases futuras (multimodal).
_SKIP_IN_BODY = {"table-wrap", "fig", "disp-formula", "supplementary-material"}


class License(StrEnum):
    CC_BY = "CC-BY"
    CC0 = "CC0"
    CC_BY_SA = "CC-BY-SA"
    CC_BY_ND = "CC-BY-ND"
    CC_BY_NC = "CC-BY-NC"  # inclui NC-SA e NC-ND
    UNKNOWN = "unknown"

    @property
    def training_allowed(self) -> bool:
        """Regra do projeto: só CC BY e CC0 entram no treino do LLM."""
        return self in (License.CC_BY, License.CC0)


def classify_license(text_or_url: str) -> License:
    s = text_or_url.lower()
    if "publicdomain/zero" in s or re.search(r"\bcc0\b", s):
        return License.CC0
    m = (
        re.search(r"licenses/([a-z-]+)/", s)
        or re.search(r"\bcc[ -]?(by(?:[ -](?:nc|sa|nd))*)\b", s)
        or re.search(r"creative commons[ -](by(?:[ -](?:nc|sa|nd))*)\b", s)
    )
    if not m:
        return License.UNKNOWN
    kind = m.group(1).replace(" ", "-")
    if "nc" in kind.split("-"):
        return License.CC_BY_NC
    if kind == "by":
        return License.CC_BY
    if kind == "by-sa":
        return License.CC_BY_SA
    if kind == "by-nd":
        return License.CC_BY_ND
    return License.UNKNOWN


@dataclass(frozen=True, slots=True)
class Paragraph:
    section: str  # caminho de seções, ex.: "Results > Photosynthesis"
    text: str


@dataclass(slots=True)
class Article:
    pmcid: str | None
    doi: str | None
    title: str
    year: int | None
    journal: str | None
    license: License
    license_source: str  # URL ou texto de onde a licença foi lida
    paragraphs: list[Paragraph] = field(default_factory=list)
    article_type: str = ""  # atributo JATS article-type, ex.: research-article, editorial

    @property
    def citable(self) -> bool:
        """Sem DOI não há citação verificável no padrão do projeto."""
        return self.doi is not None

    @property
    def key(self) -> str:
        return self.pmcid or self.doi or self.title


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_id: str
    article_key: str
    doi: str | None
    section: str
    text: str


def _text(el: Element | None) -> str:
    return _WS.sub(" ", "".join(el.itertext())).strip() if el is not None else ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# Do menos ao mais restritivo para o projeto: só CC0 e CC BY entram no treino.
_RESTRICTIVENESS = [
    License.CC0,
    License.CC_BY,
    License.CC_BY_SA,
    License.CC_BY_ND,
    License.CC_BY_NC,
]


def _find_license(meta: Element) -> tuple[License, str]:
    """Licença declarada no artigo.

    Ordem de confiança: links de licença (ali:license_ref, xlink:href do <license> e de
    <ext-link> dentro dele) antes do texto. O texto engana: a PeerJ escreve "Creative Commons
    Attribution License" com link para by-nc (caso real, PMC12642916). Se os links divergirem,
    vale o mais restritivo.
    """
    perms = meta.find("permissions")
    if perms is None:
        return License.UNKNOWN, ""
    found: list[tuple[License, str]] = []
    texts: list[str] = []
    for el in perms.iter():
        name = _local(el.tag)
        if name == "license_ref" and el.text:
            found.append((classify_license(el.text), el.text.strip()))
        elif name == "license":
            texts.append(_text(el))
            for sub in el.iter():  # o próprio <license> e qualquer <ext-link>/<uri> dentro dele
                if href := sub.get(_XLINK_HREF):
                    found.append((classify_license(href), href))
    known = [(lic, src) for lic, src in found if lic is not License.UNKNOWN]
    if known:
        return max(known, key=lambda x: _RESTRICTIVENESS.index(x[0]))
    for body in texts:
        if (lic := classify_license(body)) is not License.UNKNOWN:
            return lic, body[:200]
    return License.UNKNOWN, ""


def _walk_sections(sec: Element, path: list[str], out: list[Paragraph]) -> None:
    title = _text(sec.find("title"))
    here = [*path, title] if title else path
    label = " > ".join(here) or "Body"
    for child in sec:
        name = _local(child.tag)
        if name == "p":
            # parágrafos com figuras/tabelas embutidas: remove esses filhos antes de extrair
            for sub in list(child):
                if _local(sub.tag) in _SKIP_IN_BODY:
                    child.remove(sub)
            if txt := _text(child):
                out.append(Paragraph(section=label, text=txt))
        elif name == "sec":
            _walk_sections(child, here, out)


def parse_jats(xml: bytes | str) -> Article:
    """Converte um artigo JATS em `Article`. Levanta ValueError se não for JATS."""
    root = fromstring(xml)
    article = root if _local(root.tag) == "article" else root.find(".//article")
    if article is None:
        raise ValueError("XML não contém <article> (não parece JATS)")
    meta = article.find("front/article-meta")
    if meta is None:
        raise ValueError("JATS sem <front>/<article-meta>")

    ids = {el.get("pub-id-type", ""): (el.text or "").strip() for el in meta.findall("article-id")}
    doi = None
    if raw := ids.get("doi"):
        try:
            doi = normalize_doi(raw)
        except ValueError:
            doi = None
    pmcid = ids.get("pmcid") or ids.get("pmc")
    if pmcid and not pmcid.upper().startswith("PMC"):
        pmcid = f"PMC{pmcid}"

    year = None
    for pd in meta.findall("pub-date"):
        if (y := (pd.findtext("year") or "").strip()).isdigit():
            year = int(y)
            break

    lic, lic_src = _find_license(meta)
    paragraphs: list[Paragraph] = []
    for abstract in meta.findall("abstract"):
        if abstract.get("abstract-type") in {"graphical", "teaser"}:
            continue
        _walk_sections(abstract, ["Abstract"], paragraphs)
    body = article.find("body")
    if body is not None:
        _walk_sections(body, [], paragraphs)

    return Article(
        pmcid=pmcid.upper() if pmcid else None,
        doi=doi,
        title=_text(meta.find("title-group/article-title")),
        year=year,
        journal=_text(article.find("front/journal-meta/journal-title-group/journal-title")) or None,
        license=lic,
        license_source=lic_src,
        paragraphs=paragraphs,
        article_type=(article.get("article-type") or "").strip().lower(),
    )


def _split_long(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts, cur = [], ""
    for sent in _SENT_END.split(text):
        if cur and len(cur) + 1 + len(sent) > max_chars:
            parts.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        parts.append(cur)
    # sentenças maiores que o limite ficam inteiras: cortar no meio quebraria a citação
    return parts


def chunk_article(article: Article, max_chars: int = 1500, min_chars: int = 300) -> list[Chunk]:
    """Trechos para indexação: junta parágrafos curtos da mesma seção, quebra longos por sentença.

    Nunca mistura seções num mesmo trecho, para o localizador da citação continuar exato.
    """
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_section: str | None = None

    def flush() -> None:
        nonlocal buf
        if buf and buf_section is not None:
            for piece in _split_long(" ".join(buf), max_chars):
                chunks.append(
                    Chunk(
                        chunk_id=f"{article.key}#{len(chunks)}",
                        article_key=article.key,
                        doi=article.doi,
                        section=buf_section,
                        text=piece,
                    )
                )
        buf = []

    for p in article.paragraphs:
        if p.section != buf_section:
            flush()
            buf_section = p.section
        buf.append(p.text)
        if sum(len(t) for t in buf) >= min_chars:
            flush()
    flush()
    return chunks
