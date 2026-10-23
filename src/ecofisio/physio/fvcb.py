"""Modelo de fotossíntese C3 de Farquhar–von Caemmerer–Berry (FvCB) e ajuste de curvas A/Ci.

Esta é a implementação de REFERÊNCIA em NumPy. O kernel C++ (`ecofisio._kernels`) é testado
contra ela; qualquer divergência entre os dois é bug no kernel até prova em contrário.

Fontes e solidez:
- Modelo: Farquhar, von Caemmerer & Berry (1980), Planta 149:78–90; limitação por TPU como em
  Sharkey et al. (2007), Plant Cell Environ 30:1035–1040. Formulação padrão e consolidada.
- Constantes cinéticas e dependência de temperatura: Bernacchi et al. (2001), Plant Cell Environ
  24:253–259, medidas in vivo em tabaco, na base de Ci. Amplamente usadas, mas são de UMA espécie;
  para outras espécies o erro em Vcmax pode ser relevante.

Suposição importante: as constantes estão na base de Ci, o que equivale a assumir condutância do
mesofilo infinita (Cc = Ci). Os Vcmax e J obtidos são "aparentes" e não devem ser comparados
diretamente com valores na base de Cc.

Unidades: Ci, Γ*, Kc em µmol mol⁻¹; O, Ko em mmol mol⁻¹; A, Vcmax, J, Rd, TPU em µmol m⁻² s⁻¹.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import least_squares

_R = 8.314e-3  # kJ mol⁻¹ K⁻¹

# Bernacchi et al. (2001): parâmetro = exp(c − ΔHa / (R·T)).
_BERNACCHI = {
    "kc": (38.05, 79.43),  # µmol mol⁻¹
    "ko": (20.30, 36.38),  # mmol mol⁻¹
    "gamma_star": (19.02, 37.83),  # µmol mol⁻¹
}


class Limitation(IntEnum):
    """Processo que limita A em cada ponto (mesma codificação do kernel C++)."""

    RUBISCO = 0
    RUBP = 1
    TPU = 2


@dataclass(frozen=True, slots=True)
class FvCBConstants:
    """Constantes cinéticas na temperatura da folha (base de Ci)."""

    gamma_star: float  # ponto de compensação de CO2 na ausência de Rd, µmol mol⁻¹
    kc: float  # constante de Michaelis–Menten para CO2, µmol mol⁻¹
    ko: float  # constante de Michaelis–Menten para O2, mmol mol⁻¹
    o2: float = 210.0  # pressão parcial de O2, mmol mol⁻¹

    @property
    def km(self) -> float:
        """Constante de Michaelis efetiva: Kc·(1 + O/Ko), µmol mol⁻¹."""
        return self.kc * (1.0 + self.o2 / self.ko)


@dataclass(frozen=True, slots=True)
class FvCBParams:
    """Parâmetros fotossintéticos (aparentes, base de Ci)."""

    vcmax: float
    j: float
    rd: float
    tpu: float = float("inf")  # inf = sem limitação por TPU


def bernacchi_constants(tleaf_c: float, o2: float = 210.0) -> FvCBConstants:
    """Constantes de Bernacchi et al. (2001) na temperatura da folha `tleaf_c` (°C)."""
    if not np.isfinite(tleaf_c) or not -10.0 <= tleaf_c <= 60.0:
        raise ValueError(f"tleaf_c fora da faixa plausível (−10 a 60 °C): {tleaf_c}")
    t_k = tleaf_c + 273.15
    vals = {k: float(np.exp(c - dha / (_R * t_k))) for k, (c, dha) in _BERNACCHI.items()}
    return FvCBConstants(gamma_star=vals["gamma_star"], kc=vals["kc"], ko=vals["ko"], o2=o2)


def gross_rates(
    ci: ArrayLike, params: FvCBParams, const: FvCBConstants
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Taxas brutas limitadas por Rubisco (Wc), regeneração de RuBP (Wj) e TPU (Wp)."""
    ci_arr = np.asarray(ci, dtype=np.float64)
    gs = const.gamma_star
    wc = params.vcmax * (ci_arr - gs) / (ci_arr + const.km)
    wj = params.j * (ci_arr - gs) / (4.0 * ci_arr + 8.0 * gs)
    wp = np.full_like(ci_arr, 3.0 * params.tpu)
    return wc, wj, wp


def net_assimilation(
    ci: ArrayLike, params: FvCBParams, const: FvCBConstants
) -> tuple[NDArray[np.float64], NDArray[np.int8]]:
    """Assimilação líquida A = min(Wc, Wj, Wp) − Rd e o processo limitante em cada ponto.

    Empates são resolvidos na ordem Rubisco < RuBP < TPU, igual ao kernel C++.
    """
    wc, wj, wp = gross_rates(ci, params, const)
    stacked = np.stack([wc, wj, wp])
    lim = np.argmin(stacked, axis=0).astype(np.int8)
    a = np.min(stacked, axis=0) - params.rd
    return a, lim


@dataclass(slots=True)
class FvCBFit:
    """Resultado do ajuste de uma curva A/Ci, com incerteza."""

    params: FvCBParams
    stderr: dict[str, float]
    ci95: dict[str, tuple[float, float]] = field(default_factory=dict)
    rmse: float = float("nan")
    n_points: int = 0
    limitation: NDArray[np.int8] = field(default_factory=lambda: np.empty(0, np.int8))
    points_per_limitation: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def identifiable(self) -> bool:
        """True se cada processo ajustado tem ao menos 2 pontos que ele limita."""
        return not any(w.startswith("não identificável") for w in self.warnings)


_NAMES_BASE = ("vcmax", "j", "rd")
_BOUNDS = {"vcmax": (1.0, 500.0), "j": (1.0, 1000.0), "rd": (0.0, 20.0), "tpu": (0.5, 100.0)}


def _to_params(x: NDArray[np.float64], fit_tpu: bool) -> FvCBParams:
    return FvCBParams(
        vcmax=float(x[0]),
        j=float(x[1]),
        rd=float(x[2]),
        tpu=float(x[3]) if fit_tpu else float("inf"),
    )


def _initial_guess(
    ci: NDArray[np.float64], a: NDArray[np.float64], const: FvCBConstants, fit_tpu: bool
) -> NDArray[np.float64]:
    rd0 = 1.0
    gs = const.gamma_star
    low = (ci > gs + 20.0) & (ci < 300.0)
    high = ci > 500.0
    vc0 = (
        float(np.median((a[low] + rd0) * (ci[low] + const.km) / (ci[low] - gs)))
        if low.any()
        else 60.0
    )
    j0 = (
        float(np.median((a[high] + rd0) * (4 * ci[high] + 8 * gs) / (ci[high] - gs)))
        if high.any()
        else 1.8 * vc0
    )
    x0 = [vc0, j0, rd0]
    if fit_tpu:
        x0.append(max((float(np.max(a)) + rd0) / 3.0, 1.0))
    lo = np.array([_BOUNDS[n][0] for n in (*_NAMES_BASE, "tpu")[: len(x0)]])
    hi = np.array([_BOUNDS[n][1] for n in (*_NAMES_BASE, "tpu")[: len(x0)]])
    return np.clip(np.array(x0), lo * 1.01, hi * 0.99)


def fit_aci(
    ci: ArrayLike,
    a: ArrayLike,
    tleaf_c: float = 25.0,
    *,
    fit_tpu: bool = False,
    n_boot: int = 0,
    seed: int = 0,
) -> FvCBFit:
    """Ajusta Vcmax, J, Rd (e TPU, opcional) a uma curva A/Ci por mínimos quadrados.

    O mínimo de funções torna a superfície de erro não suave; por isso o ajuste usa várias
    partidas e fica com a de menor custo. `n_boot > 0` adiciona intervalos de 95% por bootstrap
    de resíduos (semente fixa, reprodutível).
    """
    ci_arr = np.asarray(ci, dtype=np.float64).ravel()
    a_arr = np.asarray(a, dtype=np.float64).ravel()
    if ci_arr.shape != a_arr.shape:
        raise ValueError(f"ci e a com tamanhos diferentes: {ci_arr.shape} vs {a_arr.shape}")
    if not (np.isfinite(ci_arr).all() and np.isfinite(a_arr).all()):
        raise ValueError("ci e a não podem ter NaN/inf; trate no pipeline antes do ajuste")
    names = (*_NAMES_BASE, "tpu") if fit_tpu else _NAMES_BASE
    k = len(names)
    if ci_arr.size < k + 2:
        raise ValueError(
            f"pontos insuficientes: {ci_arr.size} (mínimo {k + 2} para {k} parâmetros)"
        )

    const = bernacchi_constants(tleaf_c)
    lo = np.array([_BOUNDS[n][0] for n in names])
    hi = np.array([_BOUNDS[n][1] for n in names])

    def solve(y: NDArray[np.float64]):
        def resid(x: NDArray[np.float64]) -> NDArray[np.float64]:
            return net_assimilation(ci_arr, _to_params(x, fit_tpu), const)[0] - y

        base = _initial_guess(ci_arr, y, const, fit_tpu)
        best = None
        for scale in (0.5, 1.0, 2.0):
            x0 = np.clip(base * scale, lo * 1.01, hi * 0.99)
            res = least_squares(resid, x0, bounds=(lo, hi), method="trf", x_scale="jac")
            if best is None or res.cost < best.cost:
                best = res
        return best

    best = solve(a_arr)
    params = _to_params(best.x, fit_tpu)
    a_hat, lim = net_assimilation(ci_arr, params, const)
    resid = a_hat - a_arr
    dof = ci_arr.size - k
    s2 = float(resid @ resid) / dof
    jac = best.jac
    cov = s2 * np.linalg.pinv(jac.T @ jac)
    stderr = {n: float(np.sqrt(max(cov[i, i], 0.0))) for i, n in enumerate(names)}

    counts = {lim_.name.lower(): int((lim == lim_).sum()) for lim_ in Limitation}
    warnings: list[str] = []
    needed = {"vcmax": "rubisco", "j": "rubp", **({"tpu": "tpu"} if fit_tpu else {})}
    for pname, region in needed.items():
        if counts[region] < 2:
            warnings.append(
                f"não identificável: {pname} ({counts[region]} ponto(s) limitado(s) por {region})"
            )
    for i, n in enumerate(names):
        if np.isclose(best.x[i], lo[i], rtol=1e-3) or np.isclose(best.x[i], hi[i], rtol=1e-3):
            warnings.append(f"{n} encostou no limite do intervalo de busca ({best.x[i]:.3g})")

    fit = FvCBFit(
        params=params,
        stderr=stderr,
        rmse=float(np.sqrt(np.mean(resid**2))),
        n_points=int(ci_arr.size),
        limitation=lim,
        points_per_limitation=counts,
        warnings=warnings,
    )

    if n_boot > 0:
        rng = np.random.default_rng(seed)
        centered = resid - resid.mean()
        draws = np.empty((n_boot, k))
        for b in range(n_boot):
            y_b = a_hat - rng.choice(centered, size=centered.size, replace=True)
            draws[b] = solve(y_b).x
        fit.ci95 = {
            n: (float(np.percentile(draws[:, i], 2.5)), float(np.percentile(draws[:, i], 97.5)))
            for i, n in enumerate(names)
        }
    return fit
