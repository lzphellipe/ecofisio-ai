"""Registry de provedores: ativação por chave de ambiente e as duas entradas do Gemini."""

from __future__ import annotations

import pytest

from ecofisio.agent.providers import provedores


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch):
    for var in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    for var in ("GEMINI_MODEL", "GEMINI_MODEL_PRO", "GEMINI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)


def test_so_qwen_sem_chaves():
    ids = [p.id for p in provedores()]
    assert ids == ["qwen"]  # o local sempre; hospedados só com chave


def test_gemini_oferece_flash_e_pro_com_a_mesma_chave(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    provs = {p.id: p for p in provedores()}
    assert "gemini" in provs and "gemini-pro" in provs
    assert provs["gemini"].model == "gemini-3.8-flash"
    assert provs["gemini-pro"].model == "gemini-4-argon"
    # mesma chave e mesmo endpoint para as duas (gratuito x pago = billing no Google)
    assert provs["gemini"].api_key == provs["gemini-pro"].api_key == "k"
    assert provs["gemini"].base_url == provs["gemini-pro"].base_url
    assert provs["gemini"].kind == "openai"


def test_gemini_pro_desativavel_e_modelos_configuraveis(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("GEMINI_MODEL_PRO", "")  # vazio desativa a entrada Pro
    provs = {p.id: p for p in provedores()}
    assert "gemini-pro" not in provs
    assert provs["gemini"].model == "gemini-2.5-flash"
