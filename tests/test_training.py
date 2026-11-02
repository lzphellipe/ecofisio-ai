"""Fase 3 (fine-tuning): config, preparação do dataset, estimativa de custo e CLI de estimativa.

Não treina nada (sem GPU): o `train.py` importa torch/trl só dentro da função. Aqui testa-se tudo
que roda sem as dependências pesadas.
"""

import json

import pytest

from ecofisio.training import TrainConfig, carregar_sft, estatisticas, estimar_custo
from ecofisio.training.custo import resumo_humano


def _linha(tipo="factual", area="bioquimica", origem="destilado", fim="assistant"):
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "[]"},
        {"role": fim, "content": "{}"},
    ]
    return json.dumps({"messages": msgs, "meta": {"tipo": tipo, "area": area, "origem": origem}})


def test_config_roundtrip(tmp_path):
    cfg = TrainConfig(modelo_base="Qwen/Qwen3-4B", epocas=2)
    p = tmp_path / "cfg.json"
    cfg.salvar(p)
    lido = TrainConfig.from_json(p)
    assert lido.modelo_base == "Qwen/Qwen3-4B" and lido.epocas == 2
    assert lido.alvos == cfg.alvos and isinstance(lido.alvos, tuple)
    with pytest.raises(ValueError):
        (tmp_path / "bad.json").write_text('{"campo_inexistente": 1}', "utf-8")
        TrainConfig.from_json(tmp_path / "bad.json")


def test_carregar_sft_valida(tmp_path):
    f = tmp_path / "train.jsonl"
    f.write_text(_linha() + "\n" + _linha(area="ecologia") + "\n", "utf-8")
    ex = carregar_sft(f)
    assert len(ex) == 2 and ex[0]["messages"][0]["role"] == "system"

    # não termina em assistant → erro claro
    f.write_text(_linha(fim="user") + "\n", "utf-8")
    with pytest.raises(ValueError, match="terminar com 'assistant'"):
        carregar_sft(f)

    with pytest.raises(FileNotFoundError):
        carregar_sft(tmp_path / "nao-existe.jsonl")


def test_estatisticas(tmp_path):
    f = tmp_path / "train.jsonl"
    f.write_text(_linha(area="bioquimica") + "\n" + _linha(area="ecologia") + "\n", "utf-8")
    s = estatisticas(f)
    assert s["n"] == 2 and s["por_area"]["bioquimica"] == 1 and s["por_origem"]["destilado"] == 2


def test_estimativa_de_custo_escala_e_e_deterministica():
    a = estimar_custo(100, 3.0)
    b = estimar_custo(200, 3.0)
    assert b["tokens"] == 2 * a["tokens"]  # dobra com o nº de exemplos
    assert estimar_custo(100, 3.0) == a  # determinística
    assert estimar_custo(1, 3.0)["horas"] >= 0.05  # piso de carga do modelo
    assert "R$" in resumo_humano(a, brl_por_usd=5.4)
    with pytest.raises(ValueError):
        estimar_custo(10, 0)


def test_cli_so_estimar_nao_importa_torch(tmp_path, capsys):
    import sys

    from ecofisio.training.cli import main

    f = tmp_path / "train.jsonl"
    f.write_text("\n".join(_linha() for _ in range(5)) + "\n", "utf-8")
    rc = main(["--dados", str(f), "--epocas", "3", "--so-estimar"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "5 exemplos" in out and "Estimativa de GPU" in out
    # a CLI de estimativa não deve ter puxado torch
    assert "torch" not in sys.modules
