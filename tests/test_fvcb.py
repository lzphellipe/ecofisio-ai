"""Testes do modelo FvCB de referência.

As curvas aqui são SINTÉTICAS, geradas pelo próprio modelo com parâmetros conhecidos. Servem para
verificar que o ajuste recupera o que foi posto; não são dados experimentais.
"""

import numpy as np
import pytest

from ecofisio.physio import (
    FvCBParams,
    Limitation,
    bernacchi_constants,
    fit_aci,
    net_assimilation,
)

CI = np.array([50, 80, 100, 150, 200, 250, 300, 400, 600, 800, 1000, 1200, 1500, 1800], float)
TRUE = FvCBParams(vcmax=60.0, j=110.0, rd=1.2)


def test_bernacchi_25c_matches_published_values():
    c = bernacchi_constants(25.0)
    # Valores tabelados por Bernacchi et al. (2001) a 25 °C: 42.75, 404.9, 278.4.
    assert c.gamma_star == pytest.approx(42.75, rel=0.01)
    assert c.kc == pytest.approx(404.9, rel=0.01)
    assert c.ko == pytest.approx(278.4, rel=0.01)


def test_constants_increase_with_temperature():
    cold, warm = bernacchi_constants(15.0), bernacchi_constants(35.0)
    assert warm.gamma_star > cold.gamma_star
    assert warm.kc > cold.kc


def test_temperature_out_of_range_is_rejected():
    with pytest.raises(ValueError):
        bernacchi_constants(80.0)


def test_net_assimilation_is_minus_rd_at_gamma_star():
    c = bernacchi_constants(25.0)
    a, _ = net_assimilation([c.gamma_star], TRUE, c)
    assert a[0] == pytest.approx(-TRUE.rd, abs=1e-12)


def test_limitation_switches_from_rubisco_to_rubp():
    c = bernacchi_constants(25.0)
    _, lim = net_assimilation(CI, TRUE, c)
    assert lim[0] == Limitation.RUBISCO
    assert lim[-1] == Limitation.RUBP
    # transição única: uma vez RuBP, sempre RuBP nesta curva sem TPU
    first_rubp = int(np.argmax(lim == Limitation.RUBP))
    assert (lim[first_rubp:] == Limitation.RUBP).all()


def test_fit_recovers_parameters_without_noise():
    c = bernacchi_constants(25.0)
    a, _ = net_assimilation(CI, TRUE, c)
    fit = fit_aci(CI, a, 25.0)
    assert fit.params.vcmax == pytest.approx(TRUE.vcmax, rel=1e-3)
    assert fit.params.j == pytest.approx(TRUE.j, rel=1e-3)
    assert fit.params.rd == pytest.approx(TRUE.rd, abs=1e-2)
    assert fit.rmse < 1e-4
    assert fit.identifiable


def test_fit_with_noise_has_ci_covering_truth():
    c = bernacchi_constants(25.0)
    a, _ = net_assimilation(CI, TRUE, c)
    rng = np.random.default_rng(42)
    noisy = a + rng.normal(0.0, 0.3, size=a.size)
    fit = fit_aci(CI, noisy, 25.0, n_boot=100, seed=1)
    lo, hi = fit.ci95["vcmax"]
    assert lo < TRUE.vcmax < hi
    lo, hi = fit.ci95["j"]
    assert lo < TRUE.j < hi
    assert all(v > 0 for v in fit.stderr.values())


def test_bootstrap_is_reproducible_with_same_seed():
    c = bernacchi_constants(25.0)
    a, _ = net_assimilation(CI, TRUE, c)
    noisy = a + np.random.default_rng(0).normal(0.0, 0.3, size=a.size)
    f1 = fit_aci(CI, noisy, n_boot=30, seed=7)
    f2 = fit_aci(CI, noisy, n_boot=30, seed=7)
    assert f1.ci95 == f2.ci95


def test_fit_with_tpu_limitation():
    c = bernacchi_constants(25.0)
    true = FvCBParams(vcmax=60.0, j=110.0, rd=1.2, tpu=7.0)
    a, lim = net_assimilation(CI, true, c)
    assert (lim == Limitation.TPU).sum() >= 2
    fit = fit_aci(CI, a, fit_tpu=True)
    assert fit.params.tpu == pytest.approx(7.0, rel=1e-3)
    assert fit.params.vcmax == pytest.approx(60.0, rel=1e-2)


def test_curve_without_high_ci_flags_j_as_not_identifiable():
    c = bernacchi_constants(25.0)
    ci_low = CI[CI <= 250]
    a, _ = net_assimilation(ci_low, TRUE, c)
    fit = fit_aci(ci_low, a)
    assert not fit.identifiable
    assert any("j" in w for w in fit.warnings)


def test_rejects_nan_and_mismatched_inputs():
    with pytest.raises(ValueError):
        fit_aci([1, 2, 3, 4, 5], [1, 2, 3, 4])
    with pytest.raises(ValueError):
        fit_aci([100, 200, 300, 400, np.nan, 600], [1, 2, 3, 4, 5, 6])
