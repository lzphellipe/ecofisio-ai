"""Login "Entrar com Google": sessão assinada (HMAC), fluxo OAuth e integração com a auth da API.

Sem rede e sem Google real: a troca de code usa httpx.MockTransport e, na API, o exchange_code é
substituído. O foco é a mecânica (assinatura do cookie, expiração, state/CSRF, prioridade do
cookie sobre o Basic auth), não o Google.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ecofisio.agent import ChatReply, ResearchAgent, ToolCall
from ecofisio.api import create_app
from ecofisio.api.google_auth import GoogleOAuth, OAuthError, claims_do_id_token
from ecofisio.evidence import RetractionChecker, RetractionWatchIndex, SupportLabel
from ecofisio.evidence.verify import VerificationResult
from ecofisio.literature import parse_jats
from ecofisio.rag import LiteratureIndex

FIXTURE = Path(__file__).parent / "fixtures" / "jats_cc_by.xml"


def _oauth(**kw) -> GoogleOAuth:
    base = dict(
        client_id="cid",
        client_secret="sec",
        redirect_uri="http://localhost:8080/auth/google/callback",
        session_secret="segredo-de-teste",
        session_horas=12,
    )
    base.update(kw)
    return GoogleOAuth(**base)


def _b64url(obj: dict) -> str:
    import base64

    raw = json.dumps(obj).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


# ---- sessão assinada --------------------------------------------------------------------------
def test_sessao_roundtrip_e_assinatura_invalida():
    o = _oauth()
    tok = o.emitir_sessao(email="a@b.com", nome="Ana", sub="123")
    lida = o.ler_sessao(tok)
    assert lida and lida["email"] == "a@b.com" and lida["nome"] == "Ana"
    # adulterar o corpo quebra a verificação
    corpo, _, sig = tok.partition(".")
    assert o.ler_sessao(f"{corpo}x.{sig}") is None
    # outro segredo não valida o mesmo cookie
    assert _oauth(session_secret="outro").ler_sessao(tok) is None
    assert o.ler_sessao(None) is None and o.ler_sessao("semponto") is None


def test_sessao_expirada():
    o = _oauth(session_horas=-1)  # já nasce expirada
    assert o.ler_sessao(o.emitir_sessao(email="a@b.com", nome="A", sub="1")) is None


# ---- fluxo OAuth ------------------------------------------------------------------------------
def test_authorization_url_tem_os_parametros():
    url = _oauth().authorization_url("st4te")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=cid" in url and "state=st4te" in url and "scope=openid" in url


def test_exchange_code_decodifica_id_token():
    id_token = f"h.{_b64url({'email': 'x@y.com', 'name': 'X', 'sub': '9'})}.s"

    def handler(req: httpx.Request) -> httpx.Response:
        assert b"grant_type=authorization_code" in req.content
        return httpx.Response(200, json={"id_token": id_token})

    claims = _oauth().exchange_code("code123", transport=httpx.MockTransport(handler))
    assert claims["email"] == "x@y.com" and claims["sub"] == "9"


def test_exchange_code_falha():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="invalid_grant")

    with pytest.raises(OAuthError, match="400"):
        _oauth().exchange_code("ruim", transport=httpx.MockTransport(handler))


def test_id_token_malformado():
    with pytest.raises(OAuthError):
        claims_do_id_token("nao-e-jwt")


# ---- integração com a API ---------------------------------------------------------------------
def _agent(tmp_path):
    idx = LiteratureIndex()
    idx.add_article(parse_jats(FIXTURE.read_bytes()))
    rw = tmp_path / "rw.csv"
    rw.write_text("Record ID,OriginalPaperDOI,RetractionDOI,RetractionNature\n", "utf-8")
    checker = RetractionChecker(index=RetractionWatchIndex.from_csv(rw))
    model = ChatReply("", [ToolCall("c1", "buscar_literatura", {}, "{}")])
    return ResearchAgent(_Scripted([model]), idx, checker, FixedVerifier(SupportLabel.SUSTENTA))


class _Scripted:
    name = "roteiro"

    def __init__(self, replies):
        self.replies = list(replies)

    def chat(self, messages, tools=None):
        return self.replies.pop(0) if self.replies else ChatReply("{}")

    def close(self):
        pass


class FixedVerifier:
    name = "nli"

    def __init__(self, label):
        self.label = label

    def verify(self, claim, passage):
        return VerificationResult(self.label, 0.1, 0.9, self.name)


def test_auth_me_reporta_login_google(tmp_path):
    app = create_app(_agent(tmp_path), runs_dir=tmp_path / "runs", users={}, oauth=_oauth())
    client = TestClient(app)
    me = client.get("/auth/me").json()
    assert me["login_google"] is True and me["autenticado"] is False


def test_login_redireciona_e_seta_state(tmp_path):
    app = create_app(_agent(tmp_path), runs_dir=tmp_path / "runs", users={}, oauth=_oauth())
    client = TestClient(app)
    r = client.get("/auth/google/login", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].startswith("https://accounts.google.com/")
    assert "eco_oauth_state" in r.cookies


def test_cookie_de_sessao_autentica_rotas_protegidas(tmp_path):
    o = _oauth()
    app = create_app(_agent(tmp_path), runs_dir=tmp_path / "runs", users={}, oauth=o)
    client = TestClient(app)
    # sem cookie e com login Google configurado (users vazio), /saude exige autenticação
    assert client.get("/saude").status_code == 401
    # com o cookie de sessão válido, passa
    client.cookies.set("eco_sessao", o.emitir_sessao(email="a@b.com", nome="A", sub="1"))
    assert client.get("/saude").status_code == 200
    assert client.get("/auth/me").json()["usuario"]["email"] == "a@b.com"


def test_callback_troca_code_e_emite_sessao(tmp_path, monkeypatch):
    o = _oauth()
    monkeypatch.setattr(
        GoogleOAuth,
        "exchange_code",
        lambda self, code, **kw: {
            "email": "pesquisa@uni.br",
            "name": "Pesquisadora",
            "sub": "42",
            "email_verified": True,
        },
    )
    app = create_app(_agent(tmp_path), runs_dir=tmp_path / "runs", users={}, oauth=o)
    client = TestClient(app)
    client.cookies.set("eco_oauth_state", "st", path="/auth")
    r = client.get(
        "/auth/google/callback", params={"code": "c", "state": "st"}, follow_redirects=False
    )
    assert r.status_code == 302 and r.headers["location"] == "/"
    assert "eco_sessao" in r.cookies
    # state divergente é recusado
    client.cookies.set("eco_oauth_state", "st", path="/auth")
    ruim = client.get(
        "/auth/google/callback", params={"code": "c", "state": "OUTRO"}, follow_redirects=False
    )
    assert ruim.status_code == 400


def test_basic_auth_continua_como_fallback_com_google_ligado(tmp_path):
    # login Google ligado E usuários Basic definidos: as duas formas funcionam
    app = create_app(
        _agent(tmp_path), runs_dir=tmp_path / "runs", users={"luiz": "s3nha"}, oauth=_oauth()
    )
    client = TestClient(app)
    assert client.get("/saude").status_code == 401
    assert client.get("/saude", auth=("luiz", "s3nha")).status_code == 200
