#include "ecofisio/fvcb.hpp"

#include <gtest/gtest.h>

#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

using namespace ecofisio::fvcb;

namespace {
// Constantes de Bernacchi et al. (2001) a 25 °C, O2 = 210 mmol mol⁻¹.
constexpr double kGammaStar = 42.75;
constexpr double kKm = 404.9 * (1.0 + 210.0 / 278.4);
constexpr double kInf = std::numeric_limits<double>::infinity();
}  // namespace

TEST(FvCB, NetAssimilationIsMinusRdAtGammaStar) {
    const Point p = net_assimilation(kGammaStar, {60.0, 110.0, 1.2, kInf}, {kGammaStar, kKm});
    EXPECT_NEAR(p.a, -1.2, 1e-12);
}

TEST(FvCB, LowCiIsRubiscoLimitedHighCiIsRubpLimited) {
    const Params params{60.0, 110.0, 1.2, kInf};
    EXPECT_EQ(net_assimilation(100.0, params, {kGammaStar, kKm}).limitation, 0);
    EXPECT_EQ(net_assimilation(1500.0, params, {kGammaStar, kKm}).limitation, 1);
}

TEST(FvCB, TpuCapsAssimilation) {
    const Point p = net_assimilation(1800.0, {60.0, 110.0, 1.2, 7.0}, {kGammaStar, kKm});
    EXPECT_EQ(p.limitation, 2);
    EXPECT_NEAR(p.a, 3.0 * 7.0 - 1.2, 1e-12);
}

TEST(FvCB, BatchMatchesSinglePoint) {
    const std::vector<double> ci{100.0, 400.0, 1500.0, 200.0};
    const std::vector<std::int64_t> curve{0, 0, 0, 1};
    const std::vector<double> vcmax{60.0, 30.0}, j{110.0, 70.0}, rd{1.2, 0.8}, tpu{kInf, kInf};
    const std::vector<double> gs{kGammaStar, kGammaStar}, km{kKm, kKm};
    std::vector<double> a(ci.size());
    std::vector<std::int8_t> lim(ci.size());
    net_assimilation_batch(ci, curve, vcmax, j, rd, tpu, gs, km, a, lim);
    for (std::size_t i = 0; i < ci.size(); ++i) {
        const auto k = static_cast<std::size_t>(curve[i]);
        const Point ref = net_assimilation(ci[i], {vcmax[k], j[k], rd[k], tpu[k]}, {gs[k], km[k]});
        EXPECT_DOUBLE_EQ(a[i], ref.a);
        EXPECT_EQ(lim[i], ref.limitation);
    }
}

TEST(FvCB, BatchRejectsCurveIndexOutOfRange) {
    const std::vector<double> ci{100.0};
    const std::vector<std::int64_t> curve{1};
    const std::vector<double> one{1.0};
    std::vector<double> a(1);
    std::vector<std::int8_t> lim(1);
    EXPECT_THROW(net_assimilation_batch(ci, curve, one, one, one, one, one, one, a, lim),
                 std::invalid_argument);
}

TEST(FvCB, BatchRejectsMismatchedSizes) {
    const std::vector<double> ci{100.0, 200.0};
    const std::vector<std::int64_t> curve{0};
    const std::vector<double> one{1.0};
    std::vector<double> a(2);
    std::vector<std::int8_t> lim(2);
    EXPECT_THROW(net_assimilation_batch(ci, curve, one, one, one, one, one, one, a, lim),
                 std::invalid_argument);
}
