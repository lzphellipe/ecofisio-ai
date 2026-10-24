"""Cliente Europe PMC com transporte simulado (sem rede)."""

from pathlib import Path

import httpx
import pytest

from ecofisio.literature.europepmc import EuropePMCClient

XML = (Path(__file__).parent / "fixtures" / "jats_cc_by.xml").read_bytes()


class FakeAPI:
    """Simula duas páginas de busca e o endpoint de texto completo."""

    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/search"):
            cursor = request.url.params["cursorMark"]
            if cursor == "*":
                return httpx.Response(
                    200,
                    json={
                        "nextCursorMark": "c2",
                        "resultList": {
                            "result": [
                                {
                                    "pmcid": "PMC0000001",
                                    "doi": "10.5555/a",
                                    "title": "A",
                                    "isOpenAccess": "Y",
                                },
                                {"pmcid": "PMC0000002", "title": "B", "isOpenAccess": "N"},
                            ]
                        },
                    },
                )
            return httpx.Response(
                200,
                json={
                    "nextCursorMark": "c2",  # cursor repetido = fim
                    "resultList": {"result": [{"doi": "10.5555/c", "title": "C"}]},
                },
            )
        if path.endswith("PMC0000001/fullTextXML"):
            return httpx.Response(200, content=XML)
        return httpx.Response(404)


def client(tmp_path, api, **kw):
    t = {"now": 0.0}
    sleeps: list[float] = []

    def sleep(s):
        sleeps.append(s)
        t["now"] += s

    c = EuropePMCClient(
        tmp_path / "raw",
        email="projeto@example.org",
        transport=httpx.MockTransport(api),
        sleep=sleep,
        clock=lambda: t["now"],
        **kw,
    )
    return c, sleeps


def test_search_follows_cursor_and_stops_on_repeat(tmp_path):
    api = FakeAPI()
    c, _ = client(tmp_path, api)
    hits = list(c.search("drought AND photosynthesis", max_results=10))
    assert [h.title for h in hits] == ["A", "B", "C"]
    assert hits[0].is_open_access is True and hits[1].is_open_access is False
    assert hits[2].pmcid is None and hits[2].is_open_access is None
    first = api.requests[0].url.params
    assert first["format"] == "json" and first["cursorMark"] == "*"
    assert first["email"] == "projeto@example.org"


def test_search_respects_max_results(tmp_path):
    api = FakeAPI()
    c, _ = client(tmp_path, api)
    assert len(list(c.search("x", max_results=1))) == 1
    assert len(api.requests) == 1


def test_full_text_is_cached_read_only(tmp_path):
    api = FakeAPI()
    c, _ = client(tmp_path, api)
    assert c.full_text_xml("pmc0000001") == XML
    assert c.full_text_xml("PMC0000001") == XML
    assert sum("fullTextXML" in r.url.path for r in api.requests) == 1
    cached = tmp_path / "raw" / "PMC0000001.xml"
    assert cached.stat().st_mode & 0o222 == 0


def test_missing_full_text_returns_none(tmp_path):
    c, _ = client(tmp_path, FakeAPI())
    assert c.full_text_xml("PMC0000009") is None


def test_invalid_pmcid_rejected(tmp_path):
    c, _ = client(tmp_path, FakeAPI())
    with pytest.raises(ValueError):
        c.full_text_xml("12345")


def test_rate_limit_spaces_requests(tmp_path):
    c, sleeps = client(tmp_path, FakeAPI(), min_interval_s=0.5)
    list(c.search("x", max_results=10))  # duas páginas = duas requisições
    assert sleeps == [pytest.approx(0.5)]


def flaky(fails: int, status: int = 500, headers: dict | None = None):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= fails:
            return httpx.Response(status, headers=headers or {})
        return httpx.Response(200, content=XML)

    return handler, calls


def test_transient_500_is_retried_with_backoff(tmp_path):
    handler, calls = flaky(2)
    c, sleeps = client(tmp_path, handler, min_interval_s=0)
    assert c.full_text_xml("PMC0000001") == XML
    assert calls["n"] == 3
    assert sleeps == [1.0, 2.0]


def test_retry_after_header_is_honored(tmp_path):
    handler, _ = flaky(1, status=429, headers={"Retry-After": "7"})
    c, sleeps = client(tmp_path, handler, min_interval_s=0)
    c.full_text_xml("PMC0000001")
    assert sleeps == [7.0]


def test_persistent_500_gives_up_and_raises(tmp_path):
    handler, calls = flaky(99)
    c, _ = client(tmp_path, handler, min_interval_s=0, retries=2)
    with pytest.raises(httpx.HTTPStatusError):
        c.full_text_xml("PMC0000001")
    assert calls["n"] == 3
    assert not (tmp_path / "raw" / "PMC0000001.xml").exists()


def test_404_is_not_retried(tmp_path):
    handler, calls = flaky(99, status=404)
    c, _ = client(tmp_path, handler, min_interval_s=0)
    assert c.full_text_xml("PMC0000001") is None
    assert calls["n"] == 1


def test_network_error_is_retried(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("queda")
        return httpx.Response(200, content=XML)

    c, sleeps = client(tmp_path, handler, min_interval_s=0)
    assert c.full_text_xml("PMC0000001") == XML and sleeps == [1.0]
