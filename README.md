# ecofisio-ai

Assistente de pesquisa em **Ecofisiologia e Bioquímica Vegetal**, de nível mestrado e doutorado: um LLM open-source ajustado para o domínio, que orquestra ferramentas de análise de dados, modelos mecanísticos e preditivos, e busca na literatura com evidência verificável.

Plano completo do projeto: [IA para Ecofisiologia e Bioquímica Vegetal — Plano de Projeto](https://claude.ai/artifact/8Ksfbz9ji9rWvSwCDpZdbN).

## Estado atual (fase 1 — fundação)

| Componente | O que já faz | Onde |
| --- | --- | --- |
| Modelo FvCB de referência | A = min(Wc, Wj, Wp) − Rd, constantes de Bernacchi et al. (2001) com dependência de temperatura | `src/ecofisio/physio/fvcb.py` |
| Ajuste de curvas A/Ci | Vcmax, J, Rd e TPU opcional; erro padrão, IC 95% por bootstrap, alerta de parâmetro não identificável | `src/ecofisio/physio/fvcb.py` |
| Kernel C++ | Avaliação do FvCB em lote para muitas curvas, exposta ao Python via nanobind | `kernels/` |
| Pipeline de dados | Camadas raw → validated → processed → analytics, esquema Pandera, limpeza sempre registrada em log | `src/ecofisio/pipeline/` |
| Evidência | Citações com DOI, trecho e localizador; força da evidência; checagem de retratações | `src/ecofisio/evidence/` |
| Verificador semântico | NLI confere se o trecho sustenta a afirmação; bloqueia afirmações estritas não sustentadas | `src/ecofisio/evidence/verify.py` |
| Literatura | Busca no Europe PMC, download do JATS com cache imutável, licença lida do próprio artigo | `src/ecofisio/literature/` |
| Busca (RAG) | BM25 + embeddings opcionais com fusão RRF; cada resultado vira citação | `src/ecofisio/rag/` |

Ainda não há LLM nem dashboard: entram nas próximas etapas da fase 1 e nas fases seguintes do roadmap.

## Arquitetura do código

Duas camadas:

- **Kernel em C++20** (`kernels/`): só o que é crítico em desempenho. Cada função tem uma versão de referência em NumPy, e o kernel é testado contra ela.
- **Orquestração em Python** (`src/ecofisio/`): pipeline, modelos, evidência e, depois, agente, RAG e API. Chama o kernel pela fachada `ecofisio.kernels`, nunca direto.

O C++ segue dois trilhos: produção em `kernels/` (só gargalos medidos) e pesquisa em `research/minikernel/` (mini-kernel de inferência, sem prazo).

```text
ecofisio-ai/
├── kernels/             # C++20: include/, src/, bindings/ (nanobind), tests/ (GoogleTest)
├── src/ecofisio/
│   ├── physio/          # modelos mecanísticos (FvCB)
│   ├── pipeline/        # camadas de dados, esquemas, limpeza com log
│   ├── evidence/        # citações, força da evidência, retratações, verificador NLI
│   ├── literature/      # Europe PMC, parser JATS, montagem do corpus
│   ├── rag/             # índice BM25 + denso, fusão RRF
│   └── kernels.py       # fachada Python dos kernels C++
├── scripts/             # verificações ao vivo (ex.: smoke_europepmc.py)
├── tests/               # pytest
├── data/                # raw/ validated/ processed/ analytics/ (fora do git; DVC)
└── research/minikernel/ # trilho 2
```

## Instalação

Requer Python 3.11+, CMake 3.26+ e um compilador C++20.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"     # compila o kernel C++ via scikit-build-core
pytest
```

Testes C++ (baixam o GoogleTest):

```bash
cmake -S . -B build/cpp -DECOFISIO_BUILD_PYTHON=OFF -DECOFISIO_BUILD_CPP_TESTS=ON
cmake --build build/cpp -j && ctest --test-dir build/cpp --output-on-failure
```

## Exemplo: ajustar uma curva A/Ci

```python
from ecofisio.physio import fit_aci

fit = fit_aci(ci, a, tleaf_c=25.0, n_boot=200, seed=0)
print(fit.params.vcmax, fit.ci95["vcmax"], fit.warnings)
```

Os valores de Vcmax e J são **aparentes** (base de Ci, condutância do mesofilo infinita). As constantes de Bernacchi et al. (2001) vêm de tabaco; para outras espécies, avalie o erro antes de comparar entre estudos.

## Corpus de literatura e busca

```bash
# 1. confira a API e a sintaxe da query (este código foi testado sem rede)
python scripts/smoke_europepmc.py --email contato@exemplo.org

# 2. monte o corpus: baixa o JATS, lê a licença, indexa e registra cada artigo
ecofisio-corpus --query '"stomatal conductance" AND drought AND OPEN_ACCESS:y' \
    --max 200 --email contato@exemplo.org --out data/processed/literature
```

`corpus_report.jsonl` diz, para cada artigo encontrado, se entrou no índice e, se não, por quê. A licença fica em cada trecho; só CC BY e CC0 podem ir para o treino do LLM (`--licenses CC-BY,CC0` filtra já na indexação).

```python
from pathlib import Path

from ecofisio.rag import LiteratureIndex

idx = LiteratureIndex.load(Path("data/processed/literature"))
for hit in idx.search("drought effect on Vcmax", k=5):
    print(hit.passage.doi, hit.passage.section, hit.passage.text[:120])
citation = hit.to_citation()  # DOI + trecho + seção, pronto para um Claim
```

Embeddings densos (`pip install -e ".[rag]"`, `--embedder <modelo>`) e o verificador semântico (`pip install -e ".[nli]"`, `NLIVerifier(<modelo>)`) são opcionais e não têm modelo padrão: escolha, valide num conjunto anotado e registre o nome. Sem verificador, a auditoria bloqueia afirmações citadas em vez de aprová-las.

## Princípios

- Dados brutos nunca são alterados; toda limpeza gera registro do que saiu e por quê.
- O sistema nunca gera nem completa dados experimentais.
- Todo modelo é comparado com uma referência simples, e todo resultado vem com incerteza.
- Validação cruzada agrupada por planta, parcela ou experimento, nunca por linha.
- Só texto CC BY/CC0 ou dados próprios entram no treino do LLM.
