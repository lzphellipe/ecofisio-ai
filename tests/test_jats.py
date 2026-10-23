from pathlib import Path

import pytest

from ecofisio.literature import License, chunk_article, classify_license, parse_jats

FIXTURE = Path(__file__).parent / "fixtures" / "jats_cc_by.xml"


@pytest.fixture(scope="module")
def article():
    return parse_jats(FIXTURE.read_bytes())


def test_metadata(article):
    assert article.pmcid == "PMC0000001"
    assert article.doi == "10.5555/test.drought.001"
    assert article.title == "Drought reduces Vcmax in coffee seedlings"
    assert article.year == 2024
    assert article.journal == "Journal of Test Plant Physiology"


def test_license_read_from_article(article):
    assert article.license is License.CC_BY
    assert article.license.training_allowed
    assert "creativecommons.org/licenses/by/4.0" in article.license_source


def test_sections_paths_and_exclusions(article):
    sections = [p.section for p in article.paragraphs]
    assert sections[0] == "Abstract"
    assert "Results > Gas exchange" in sections
    text = " ".join(p.text for p in article.paragraphs)
    assert "Graphical abstract" not in text
    assert "Figure caption" not in text
    assert "[1]" in text  # referências cruzadas ficam no texto


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://creativecommons.org/licenses/by/4.0/", License.CC_BY),
        ("http://creativecommons.org/licenses/by-nc-nd/4.0/", License.CC_BY_NC),
        ("https://creativecommons.org/licenses/by-sa/3.0/", License.CC_BY_SA),
        ("https://creativecommons.org/publicdomain/zero/1.0/", License.CC0),
        ("This is an open access article under the CC BY-NC license.", License.CC_BY_NC),
        ("All rights reserved.", License.UNKNOWN),
    ],
)
def test_classify_license(raw, expected):
    assert classify_license(raw) is expected


def test_nc_and_unknown_not_allowed_for_training():
    assert not License.CC_BY_NC.training_allowed
    assert not License.UNKNOWN.training_allowed
    assert not License.CC_BY_SA.training_allowed


def test_chunks_never_cross_sections(article):
    chunks = chunk_article(article, max_chars=300, min_chars=150)
    by_text = {c.text: c.section for c in chunks}
    assert all(c.doi == "10.5555/test.drought.001" for c in chunks)
    intro = [c for c in chunks if c.section == "Introduction"]
    assert len(intro) == 1  # dois parágrafos curtos juntados
    assert "Stomatal closure" in intro[0].text and "debated" in intro[0].text
    assert any(sec == "Results > Fluorescence" for sec in by_text.values())
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_long_paragraph_split_by_sentence(article):
    chunks = chunk_article(article, max_chars=60, min_chars=10)
    gas = [c for c in chunks if c.section == "Results > Gas exchange"]
    assert len(gas) == 2
    assert gas[1].text.startswith("Net assimilation")


def test_article_without_doi_is_not_citable():
    xml = b"""<article><front><article-meta><article-id pub-id-type="pmcid">123</article-id>
    <title-group><article-title>X</article-title></title-group></article-meta></front></article>"""
    a = parse_jats(xml)
    assert a.pmcid == "PMC123" and not a.citable and a.license is License.UNKNOWN


def test_non_jats_rejected():
    with pytest.raises(ValueError):
        parse_jats(b"<html><body>not jats</body></html>")


def test_external_entities_are_blocked():
    evil = b"""<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]>
    <article><front><article-meta><title-group><article-title>&x;</article-title>
    </title-group></article-meta></front></article>"""
    with pytest.raises(Exception):  # noqa: B017 (defusedxml levanta tipos variados)
        parse_jats(evil)
