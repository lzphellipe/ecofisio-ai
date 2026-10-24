# Benchmarks

Conjuntos de perguntas para avaliar o assistente com `ecofisio-eval`. Formato e tipos em `src/ecofisio/eval/benchmark.py`.

| Arquivo | Itens | Situação |
| --- | --- | --- |
| `semente.jsonl` | 13 (8 factuais, 3 fora do escopo, 2 armadilhas) | Escrito sem especialista: serve para testar o avaliador e comparar configurações, não como medida final de qualidade |

Regras:

- **É conjunto de teste.** Não ajuste prompt, modelo nem dataset de treino olhando as respostas a estas perguntas. Para ajustar, crie um conjunto separado de desenvolvimento.
- **Não edite um arquivo já usado em resultados.** O hash do arquivo vai para cada relatório; mudar o conteúdo torna as execuções incomparáveis. Crie uma versão nova (`semente_v2.jsonl`).
- `dois_esperados` só lista artigos que um especialista confirmou que respondem a pergunta. O avaliador avisa quando um DOI esperado não está no índice.
- O benchmark da fase 2 (300+ questões de banca, corrigidas às cegas por doutores) substitui este conjunto como medida de qualidade.
