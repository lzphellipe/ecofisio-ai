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
| Busca (RAG) | BM25 + embeddings opcionais com fusão RRF; cada resultado vira citação; tipo de publicação em cada trecho | `src/ecofisio/rag/` |
| Avaliador | Benchmark versionado, métricas de rigor (citações inventadas, bloqueios por motivo, abstenção fora do escopo), IC 95% por bootstrap e comparação pareada entre execuções | `src/ecofisio/eval/`, `benchmarks/` |
| Agente base | LLM (qualquer servidor compatível com OpenAI) + busca; responde em afirmações que citam IDs de trechos; cada afirmação é auditada antes de sair | `src/ecofisio/agent/` |

Ainda não há dashboard: entra no começo da fase 2.

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
│   ├── agent/           # cliente de LLM, ferramentas, agente de pesquisa, CLI ecofisio-ask
│   ├── eval/            # benchmark, métricas, relatório e comparação (ecofisio-eval)
│   └── kernels.py       # fachada Python dos kernels C++
├── benchmarks/          # conjuntos de perguntas de teste (JSONL versionado)
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
# 1. confira a API e a sintaxe da query
python scripts/smoke_europepmc.py --email contato@exemplo.org

# 2. monte o corpus: baixa o JATS, lê a licença, indexa e registra cada artigo
ecofisio-corpus --query-file queries/seca_trocas_gasosas.txt --max 200 --licenses CC-BY,CC0 --email contato@exemplo.org
```

As queries ficam em `queries/`, versionadas: a busca que gerou o corpus é reproduzível (requisito da revisão sistemática). Prefira `--query-file` a `--query` no Windows: o PowerShell remove as aspas duplas internas ao passar argumentos para programas externos.

Para consultar o corpus direto, sem modelo:

```powershell
ecofisio-busca "stomatal conductance drought recovery" -k 10 --so-primarios
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

## Perguntar ao assistente (LLM base + RAG)

O modelo roda numa GPU alugada com vLLM; o guia passo a passo está em [`docs/llm-base-brev.md`](docs/llm-base-brev.md).

```powershell
ecofisio-ask "Qual o efeito da seca sobre o Vcmax?" --crossref-email contato@exemplo.org
```

O modelo nunca escreve o trecho que cita: ele cita IDs (T1, T2...) dos trechos que a busca devolveu, e a citação é montada a partir do texto real. Afirmações com ID inexistente, força da evidência exagerada, artigo retratado ou trecho que não as sustenta voltam como **bloqueadas**, com o motivo.

## Avaliar o assistente

```powershell
ecofisio-eval run --benchmark benchmarks/semente.jsonl --rotulo qwen3-4b-cpu --crossref-email contato@exemplo.org --sem-verificacao-semantica
ecofisio-eval compare runs/eval/<execucao-A>/resultados.json runs/eval/<execucao-B>/resultados.json
```

Cada execução grava em `runs/eval/<data>_<rotulo>/` o relatório (`relatorio.md`), os números (`resultados.json`) e o rastro completo de cada pergunta. O relatório traz IC 95% por bootstrap sobre as perguntas; a comparação usa bootstrap pareado e só declara "B melhor" quando o intervalo da diferença exclui zero. Execuções com versões diferentes do benchmark não são comparadas.

Métricas: perguntas com erro, perguntas sem busca, fração de afirmações bloqueadas e o motivo de cada bloqueio, citações inventadas por pergunta, recall dos DOIs esperados, abstenção correta nas perguntas fora do escopo, latência e tokens. As armadilhas (premissa falsa) ficam marcadas para revisão humana.

## Princípios

- Dados brutos nunca são alterados; toda limpeza gera registro do que saiu e por quê.
- O sistema nunca gera nem completa dados experimentais.
- Todo modelo é comparado com uma referência simples, e todo resultado vem com incerteza.
- Validação cruzada agrupada por planta, parcela ou experimento, nunca por linha.
- Só texto CC BY/CC0 ou dados próprios entram no treino do LLM.
