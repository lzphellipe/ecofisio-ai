// Ponte Python ↔ C++ via nanobind. API pequena e estável: o Python passa arrays NumPy 1D
// contíguos e recebe arrays NumPy; não vê nada de layout interno.
#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include <cstdint>
#include <span>

#include "ecofisio/fvcb.hpp"

namespace nb = nanobind;

namespace {

template <typename T>
using In = nb::ndarray<const T, nb::ndim<1>, nb::c_contig, nb::device::cpu>;

template <typename T>
std::span<const T> as_span(const In<T>& a) {
    return {a.data(), a.shape(0)};
}

template <typename T>
nb::ndarray<nb::numpy, T, nb::ndim<1>> owned(std::size_t n, T*& out) {
    out = new T[n];  // posse transferida para a cápsula abaixo, que libera com delete[]
    nb::capsule owner(out, [](void* p) noexcept { delete[] static_cast<T*>(p); });
    return nb::ndarray<nb::numpy, T, nb::ndim<1>>(out, {n}, owner);
}

nb::tuple fvcb_batch(In<double> ci, In<std::int64_t> curve, In<double> vcmax, In<double> j,
                     In<double> rd, In<double> tpu, In<double> gamma_star, In<double> km) {
    const std::size_t n = ci.shape(0);
    double* a_ptr = nullptr;
    std::int8_t* lim_ptr = nullptr;
    auto a = owned<double>(n, a_ptr);
    auto lim = owned<std::int8_t>(n, lim_ptr);
    {
        nb::gil_scoped_release release;
        ecofisio::fvcb::net_assimilation_batch(
            as_span(ci), as_span(curve), as_span(vcmax), as_span(j), as_span(rd), as_span(tpu),
            as_span(gamma_star), as_span(km), std::span<double>(a_ptr, n),
            std::span<std::int8_t>(lim_ptr, n));
    }
    return nb::make_tuple(a, lim);
}

}  // namespace

NB_MODULE(_kernels, m) {
    m.doc() = "Kernels C++ do ecofisio-ai (testados contra a referência em NumPy).";
    m.def("fvcb_net_assimilation_batch", &fvcb_batch, nb::arg("ci"), nb::arg("curve"),
          nb::arg("vcmax"), nb::arg("j"), nb::arg("rd"), nb::arg("tpu"), nb::arg("gamma_star"),
          nb::arg("km"),
          "Avalia o FvCB para n pontos de m curvas. Retorna (a, limitation) como arrays NumPy.");
}
