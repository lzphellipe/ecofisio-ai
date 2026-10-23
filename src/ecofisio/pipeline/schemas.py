"""Esquemas de validação dos dados de campo (camada validated).

As faixas são de PLAUSIBILIDADE física e de equipamento, não limites fisiológicos exatos: servem
para pegar erro de digitação, sensor travado ou unidade trocada. Para uma espécie ou condição
específica, crie um esquema derivado com faixas mais apertadas.

Nomes de coluna em snake_case; unidades no comentário de cada campo.
"""

from __future__ import annotations

import pandera.pandas as pa
from pandera.typing.pandas import Series

# Cabeçalhos típicos do LI-6800 → nomes internos. Confira contra o seu arquivo exportado:
# versões de firmware e configurações de exportação mudam nomes de coluna.
LI6800_COLUMNS: dict[str, str] = {
    "A": "a",
    "Ci": "ci",
    "gsw": "gsw",
    "Tleaf": "tleaf",
    "Qin": "qin",
}


class GasExchangeSchema(pa.DataFrameModel):
    """Uma linha = uma leitura de trocas gasosas em uma folha."""

    sample_id: Series[str] = pa.Field(unique=True)  # identificador único da leitura
    plant_id: Series[str]  # unidade experimental (usada para agrupar na validação cruzada)
    treatment: Series[str]
    a: Series[float] = pa.Field(ge=-20.0, le=80.0)  # assimilação líquida, µmol m⁻² s⁻¹
    ci: Series[float] = pa.Field(ge=0.0, le=3000.0)  # CO2 intercelular, µmol mol⁻¹
    gsw: Series[float] = pa.Field(ge=0.0, le=3.0)  # condutância estomática, mol m⁻² s⁻¹
    tleaf: Series[float] = pa.Field(ge=-5.0, le=55.0)  # temperatura da folha, °C
    qin: Series[float] = pa.Field(ge=0.0, le=3000.0)  # PAR incidente, µmol m⁻² s⁻¹

    class Config:
        strict = False  # colunas extras do equipamento são mantidas
        coerce = True


class FluorescenceSchema(pa.DataFrameModel):
    """Uma linha = uma medida de fluorescência da clorofila adaptada ao escuro.

    Fv/Fm até 0,90: o plano cita 0,85 como teto, mas folhas sadias chegam a 0,86–0,87 e um teto
    de 0,85 rejeitaria leituras legítimas.
    """

    sample_id: Series[str] = pa.Field(unique=True)
    plant_id: Series[str]
    treatment: Series[str]
    f0: Series[float] = pa.Field(gt=0.0)  # fluorescência mínima (unidade relativa do equipamento)
    fm: Series[float] = pa.Field(gt=0.0)  # fluorescência máxima
    fv_fm: Series[float] = pa.Field(ge=0.0, le=0.90)  # rendimento quântico máximo do PSII

    @pa.dataframe_check
    def fm_greater_than_f0(cls, df) -> Series[bool]:  # noqa: N805 (convenção do pandera)
        return df["fm"] > df["f0"]

    class Config:
        strict = False
        coerce = True
