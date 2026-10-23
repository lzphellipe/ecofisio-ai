// Modelo FvCB (Farquhar–von Caemmerer–Berry) em C++20 — núcleo sem dependência de Python.
//
// Referência numérica: src/ecofisio/physio/fvcb.py. Este código precisa reproduzir aquela
// implementação dentro da tolerância dos testes; a de Python é a fonte da verdade.
//
// Unidades: Ci, Γ*, Km em µmol mol⁻¹; Vcmax, J, Rd, TPU e A em µmol m⁻² s⁻¹.
// Codificação do processo limitante: 0 = Rubisco, 1 = RuBP, 2 = TPU (empates: menor código).
#pragma once

#include <cstdint>
#include <span>

namespace ecofisio::fvcb {

struct Constants {
    double gamma_star;  // ponto de compensação de CO2 sem Rd
    double km;          // Kc·(1 + O/Ko)
};

struct Params {
    double vcmax;
    double j;
    double rd;
    double tpu;  // +inf desliga a limitação por TPU
};

struct Point {
    double a;
    std::int8_t limitation;
};

// Assimilação líquida em um ponto.
[[nodiscard]] Point net_assimilation(double ci, const Params& p, const Constants& c) noexcept;

// Avaliação em lote de muitas curvas de uma vez.
//
// Layout (todos contíguos, tamanhos verificados):
//   ci, curve           : n pontos; curve[i] ∈ [0, m) indica a curva do ponto i
//   vcmax, j, rd, tpu,
//   gamma_star, km      : m curvas (parâmetros e constantes por curva, ex.: temperaturas diferentes)
//   a_out, lim_out      : n pontos (saída)
//
// Lança std::invalid_argument se os tamanhos não baterem ou se curve[i] estiver fora de [0, m).
void net_assimilation_batch(std::span<const double> ci, std::span<const std::int64_t> curve,
                            std::span<const double> vcmax, std::span<const double> j,
                            std::span<const double> rd, std::span<const double> tpu,
                            std::span<const double> gamma_star, std::span<const double> km,
                            std::span<double> a_out, std::span<std::int8_t> lim_out);

}  // namespace ecofisio::fvcb
