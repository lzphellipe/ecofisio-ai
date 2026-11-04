"""Login "Entrar com Google" (OAuth2) para o app — identidade do usuário, separada do acesso à LLM.

O que isto faz e o que NÃO faz:
- Faz: descobre QUEM é o usuário (e-mail, nome) por OAuth2 com o Google, e emite um cookie de
  sessão assinado (HMAC). O acesso aos modelos continua sendo configuração do servidor (as chaves
  dos provedores), sem relação com quem logou.
- Não faz: não dá acesso a nenhuma API de LLM. Login Google != chave de API do Gemini/Vertex.

Config por ambiente (tudo opcional: sem GOOGLE_OAUTH_CLIENT_ID o login fica desligado e o app segue
no Basic auth):
    GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET   do OAuth Client (Web) no Google Cloud
    GOOGLE_OAUTH_REDIRECT    URL de callback (padrão <base>/auth/google/callback)
    ECOFISIO_SESSION_SECRET  segredo para assinar o cookie de sessão (gere um aleatório e fixe)
    ECOFISIO_SESSION_HORAS   validade da sessão em horas (padrão 12)

Escolha do projeto: qualquer conta Google pode entrar (sem restrição de domínio). Para restringir
a um domínio Workspace depois, basta filtrar o claim `hd`/`email` no callback.

O id_token vem direto do endpoint de token do Google por HTTPS (troca servidor-a-servidor), então
seus claims são confiáveis sem re-verificar a assinatura — conforme a doc do Google. Mesmo assim o
cookie de sessão que EMITIMOS é sempre verificado por HMAC a cada requisição.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "openid email profile"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@dataclass(frozen=True, slots=True)
class GoogleOAuth:
    client_id: str
    client_secret: str
    redirect_uri: str
    session_secret: str
    session_horas: int = 12

    @classmethod
    def from_env(cls) -> GoogleOAuth | None:
        cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
        if not (cid and secret):
            return None
        return cls(
            client_id=cid,
            client_secret=secret,
            redirect_uri=os.environ.get(
                "GOOGLE_OAUTH_REDIRECT", "http://localhost:8080/auth/google/callback"
            ),
            # sem segredo fixo, cada boot invalida as sessões (aceitável, mas avisável)
            session_secret=os.environ.get("ECOFISIO_SESSION_SECRET") or _b64url(os.urandom(32)),
            session_horas=int(os.environ.get("ECOFISIO_SESSION_HORAS", "12")),
        )

    # ---- fluxo OAuth ----------------------------------------------------------------------
    def authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(
        self, code: str, *, transport: httpx.BaseTransport | None = None
    ) -> dict[str, object]:
        """Troca o code por tokens e devolve os claims do id_token (email, name, sub...)."""
        data = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        with httpx.Client(timeout=30.0, transport=transport) as http:
            resp = http.post(TOKEN_URL, data=data)
        if resp.status_code != 200:
            raise OAuthError(f"troca de code falhou: HTTP {resp.status_code} {resp.text[:300]}")
        id_token = resp.json().get("id_token")
        if not id_token:
            raise OAuthError("resposta do Google sem id_token")
        return claims_do_id_token(id_token)

    # ---- sessão (cookie assinado por HMAC) ------------------------------------------------
    def emitir_sessao(self, *, email: str, nome: str, sub: str) -> str:
        exp = int(time.time()) + self.session_horas * 3600
        payload = {"email": email, "nome": nome, "sub": sub, "exp": exp}
        corpo = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        assinatura = _b64url(
            hmac.new(
                self.session_secret.encode("utf-8"), corpo.encode("ascii"), hashlib.sha256
            ).digest()
        )
        return f"{corpo}.{assinatura}"

    def ler_sessao(self, token: str | None) -> dict[str, object] | None:
        """Valida o cookie: assinatura confere E não expirou. Caso contrário, None."""
        if not token or "." not in token:
            return None
        corpo, _, assinatura = token.partition(".")
        esperada = _b64url(
            hmac.new(
                self.session_secret.encode("utf-8"), corpo.encode("ascii"), hashlib.sha256
            ).digest()
        )
        if not hmac.compare_digest(assinatura, esperada):
            return None
        try:
            payload = json.loads(_b64url_decode(corpo))
        except (ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or payload.get("exp", 0) < time.time():
            return None
        return payload


class OAuthError(RuntimeError):
    """Falha no fluxo OAuth (troca de code, id_token ausente, etc.)."""


def claims_do_id_token(id_token: str) -> dict[str, object]:
    """Decodifica o payload do id_token (JWT). Sem re-verificar a assinatura: veio do Google por
    HTTPS na troca servidor-a-servidor. Levanta OAuthError se malformado."""
    partes = id_token.split(".")
    if len(partes) != 3:
        raise OAuthError("id_token malformado")
    try:
        return json.loads(_b64url_decode(partes[1]))
    except (ValueError, json.JSONDecodeError) as exc:
        raise OAuthError(f"id_token ilegível: {exc}") from exc
