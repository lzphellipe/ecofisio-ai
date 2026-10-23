# Instruções para agentes neste repositório

Use a skill `engenheira-ia-ml` ao trabalhar aqui. Plano do projeto: https://claude.ai/artifact/8Ksfbz9ji9rWvSwCDpZdbN

Regras que não podem ser quebradas:

- Toda função em `kernels/` tem uma referência em NumPy em `src/ecofisio/` e um teste comparando as duas com tolerância explícita. A referência em Python é a fonte da verdade.
- O resto do código chama o C++ só pela fachada `ecofisio.kernels`.
- Nenhum dado é removido ou alterado sem entrada no `ProcessingLog`; dado bruto em `data/raw/` é imutável; nada imputa valores experimentais.
- Toda afirmação entregue ao pesquisador é um `Claim` com citação (DOI + trecho), força da evidência e auditoria de retratação; "não verificado" nunca é tratado como "limpo".
- Validação cruzada agrupada por planta, parcela ou experimento, nunca por linha.
- Antes de qualquer job de GPU, estimar GPU, horas e custo e pedir confirmação.

Comandos:

```bash
pip install -e ".[dev]"                   # compila o kernel e instala
pytest                                    # testes Python
ruff check src tests && ruff format --check src tests
cmake -S . -B build/cpp -DECOFISIO_BUILD_PYTHON=OFF -DECOFISIO_BUILD_CPP_TESTS=ON
cmake --build build/cpp -j && ctest --test-dir build/cpp --output-on-failure
```
