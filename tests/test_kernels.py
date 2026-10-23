"""O kernel C++ precisa reproduzir a referência NumPy (tolerância explícita abaixo)."""

import numpy as np
import pytest

from ecofisio.physio import FvCBParams, bernacchi_constants, net_assimilation

kernels = pytest.importorskip("ecofisio.kernels", reason="módulo C++ não compilado")

RTOL, ATOL = 1e-12, 1e-12


def test_batch_matches_numpy_reference_across_many_curves():
    rng = np.random.default_rng(123)
    m = 200
    params = [
        FvCBParams(
            vcmax=float(rng.uniform(20, 150)),
            j=float(rng.uniform(50, 300)),
            rd=float(rng.uniform(0.3, 3.0)),
            tpu=float(rng.uniform(5, 20)) if rng.random() < 0.5 else float("inf"),
        )
        for _ in range(m)
    ]
    consts = [bernacchi_constants(float(t)) for t in rng.uniform(15, 35, size=m)]
    ci = np.tile(np.linspace(30, 2000, 13), m)
    curve = np.repeat(np.arange(m), 13)

    a_cpp, lim_cpp = kernels.fvcb_batch(ci, curve, params, consts)

    a_ref = np.empty_like(ci)
    lim_ref = np.empty(ci.size, dtype=np.int8)
    for k in range(m):
        idx = curve == k
        a_ref[idx], lim_ref[idx] = net_assimilation(ci[idx], params[k], consts[k])

    np.testing.assert_allclose(a_cpp, a_ref, rtol=RTOL, atol=ATOL)
    np.testing.assert_array_equal(lim_cpp, lim_ref)


def test_batch_rejects_bad_curve_index():
    c = bernacchi_constants(25.0)
    with pytest.raises(ValueError):
        kernels.fvcb_batch([100.0], [3], [FvCBParams(60, 110, 1)], [c])


def test_batch_rejects_params_constants_mismatch():
    c = bernacchi_constants(25.0)
    with pytest.raises(ValueError):
        kernels.fvcb_batch([100.0], [0], [FvCBParams(60, 110, 1)], [c, c])
