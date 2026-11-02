# Dataset de SFT (fase 2) por destilação

O dataset de fine-tuning é gerado por **destilação**: o agente base (modelo open-source + RAG)
responde a um conjunto de perguntas-semente, e só as respostas que passam no portão de qualidade
viram alvo de treino. As recusas de uso duplo não são geradas pelo modelo — são escritas à mão em
`src/ecofisio/dataset/seeds.py`, para o alvo ser sempre uma recusa limpa.

O fine-tuning ensina **comportamento** (citar com DOI, calibrar "não sei", recusar uso duplo,
chamar as ferramentas), não fatos. Por isso o portão é severo: ensina-se só o que foi verificado.

## Pré-requisito de licença

A destilação deve usar um índice montado **só com licenças de treino** (CC BY/CC0), para todo
trecho citado já ser liberado para fine-tuning:

Monte o corpus com **todas as áreas** que as sementes cobrem (uma query por área):

```bash
ecofisio-corpus \
  --query-file queries/bioquimica.txt \
  --query-file queries/biologia_celular.txt \
  --query-file queries/genetica_expressao.txt \
  --query-file queries/imunologia.txt \
  --query-file queries/microbiologia.txt \
  --query-file queries/seca_trocas_gasosas.txt \
  --query-file queries/ecologia.txt \
  --query-file queries/evolucao.txt \
  --query-file queries/fisiologia_animal.txt \
  --licenses CC-BY,CC0 --max 150 --email voce@exemplo.org \
  --out data/processed/literature-treino
```

(NC pode entrar no índice de **busca** do assistente, mas nunca no índice de destilação.)

## Gerar o dataset

Precisa de um LLM vivo, como o `ecofisio-ask`: suba a base no Brev (ver
[`llm-base-brev.md`](llm-base-brev.md)) e abra o túnel SSH. Então, na pasta do repositório:

```powershell
$env:ECOFISIO_LLM_KEY = "<a chave do servidor>"
ecofisio-dataset --index data/processed/literature-treino `
  --crossref-email voce@exemplo.org --sem-verificacao-semantica `
  --out data/sft
```

Saída em `data/sft/`:

- `train.jsonl` / `val.jsonl` — exemplos no padrão chat (split determinístico por pergunta, sem vazamento).
- `manifest.json` — contagens por tipo/área/nível, DOIs citados, modelo destilador e `sha256` do treino.
- `descartados.jsonl` — perguntas que não passaram no portão, com o motivo (para inspeção).

Enquanto não houver um modelo NLI escolhido, `--sem-verificacao-semantica` deixa as afirmações
entrarem com aviso; com um verificador (`--nli-model`), o portão fica mais rigoroso.

## Baixar o resultado para o seu PC (automatizado)

A VM não empurra arquivos para o seu PC, então o download roda do seu lado, num comando só.
No **WSL/PC** (onde o `brev` está logado), da pasta do repositório:

```bash
# baixa dataset + rastros das perguntas + projetos/artefatos (+ saídas de treino, quando houver)
bash scripts/baixar_dados.sh                 # da instância eco-bio-vllm, para ./ecofisio-dados

# ou: gera o dataset na VM e já baixa (o vLLM precisa estar no ar)
GERAR=1 LLM_KEY=<chave-do-vllm> bash scripts/baixar_dados.sh
```

Se o nome da instância não resolver no ssh, passe o host explícito (painel do Brev → TCP/UDP
Ports, porta 22): `SSH_HOST=global.prd.ga.run.brev.nvidia.com SSH_PORT=<porta> bash scripts/baixar_dados.sh`.

## Próximo passo

Com o dataset em mãos, o treino em si (QLoRA sobre o Qwen 3, numa GPU L40S/A100 do Brev) é a fase
3. Antes de disparar, estime GPU, horas e custo e confirme — regra do `CLAUDE.md`.
