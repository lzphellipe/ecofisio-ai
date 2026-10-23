#include "ecofisio/fvcb.hpp"

#include <cstddef>
#include <stdexcept>
#include <string>

namespace ecofisio::fvcb {

Point net_assimilation(double ci, const Params& p, const Constants& c) noexcept {
    const double d = ci - c.gamma_star;
    const double wc = p.vcmax * d / (ci + c.km);
    const double wj = p.j * d / (4.0 * ci + 8.0 * c.gamma_star);
    const double wp = 3.0 * p.tpu;

    // Mesma regra de desempate do np.argmin: o primeiro mínimo vence.
    double w = wc;
    std::int8_t lim = 0;
    if (wj < w) {
        w = wj;
        lim = 1;
    }
    if (wp < w) {
        w = wp;
        lim = 2;
    }
    return {w - p.rd, lim};
}

void net_assimilation_batch(std::span<const double> ci, std::span<const std::int64_t> curve,
                            std::span<const double> vcmax, std::span<const double> j,
                            std::span<const double> rd, std::span<const double> tpu,
                            std::span<const double> gamma_star, std::span<const double> km,
                            std::span<double> a_out, std::span<std::int8_t> lim_out) {
    const std::size_t n = ci.size();
    const std::size_t m = vcmax.size();
    if (curve.size() != n || a_out.size() != n || lim_out.size() != n) {
        throw std::invalid_argument("ci, curve, a_out e lim_out precisam ter o mesmo tamanho");
    }
    if (j.size() != m || rd.size() != m || tpu.size() != m || gamma_star.size() != m ||
        km.size() != m) {
        throw std::invalid_argument(
            "vcmax, j, rd, tpu, gamma_star e km precisam ter o mesmo tamanho (uma entrada por curva)");
    }
    for (std::size_t i = 0; i < n; ++i) {
        const std::int64_t k = curve[i];
        if (k < 0 || static_cast<std::size_t>(k) >= m) {
            throw std::invalid_argument("curve[" + std::to_string(i) + "] = " + std::to_string(k) +
                                        " fora de [0, " + std::to_string(m) + ")");
        }
    }
    for (std::size_t i = 0; i < n; ++i) {
        const auto k = static_cast<std::size_t>(curve[i]);
        const Point pt = net_assimilation(ci[i], Params{vcmax[k], j[k], rd[k], tpu[k]},
                                          Constants{gamma_star[k], km[k]});
        a_out[i] = pt.a;
        lim_out[i] = pt.limitation;
    }
}

}  // namespace ecofisio::fvcb
