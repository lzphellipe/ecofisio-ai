# Fine-tuning QLoRA (fase 3)

Ajusta o modelo base (padrão **Qwen3-4B**) sobre o dataset de SFT (`data/sft/train.jsonl`). O
fine-tuning ensina **comportamento** — citar com DOI, calibrar "não sei", recusar uso duplo, chamar
as ferramentas —, não fatos; estes seguem vindo do RAG. Por isso o **critério de aceite** é superar
o "base + RAG" no benchmark (`ecofisio-eval`), com alucinação baixa e citações verificáveis.

Precisa de GPU (24 GB serve para o 4B em 4 bits). Roda no Brev.

## 1. Pré-requisitos

- Um `data/sft/train.jsonl` com exemplos suficientes. O dataset de validação do pipeline (poucos
  exemplos) **não serve** para um ajuste útil — amplie o corpus e as sementes e regenere antes.
- Dependências de treino: `pip install -e ".[train]"` (torch, transformers, peft, trl,
  bitsandbytes, accelerate, datasets).

## 2. Estimar o custo (sempre, antes de treinar)

```bash
ecofisio-train --dados data/sft/train.jsonl --epocas 3 --brl 5.4 --so-estimar
```

Mostra as estatísticas do dataset e uma estimativa de GPU-horas/custo (ordem de grandeza). Regra
do projeto: **nada de job de GPU sem confirmar**.

## 3. Treinar

```bash
ecofisio-train --dados data/sft/train.jsonl --epocas 3 --saida outputs/qlora
# ele repete a estimativa e pergunta "Confirmar o treino na GPU? (s/N)"; --sim pula a pergunta
```

Salva o **adaptador LoRA** em `outputs/qlora/` (poucas centenas de MB — leve de baixar/versionar).
Opções: `--modelo-base Qwen/Qwen3-8B` para comparar com o 8B, `--config cfg.json` para ajustar
hiperparâmetros (r, alpha, lr, épocas…).

## 4. Avaliar (o que decide se valeu)

Sirva o base + adaptador (vLLM aceita `--enable-lora`/adaptador) e compare contra o base + RAG:

```bash
ecofisio-eval run --rotulo qwen3-4b-qlora ...        # com o modelo ajustado
ecofisio-eval compare runs/eval/<base>/resultados.json runs/eval/<ajustado>/resultados.json
```

Só declare melhoria quando o `compare` (bootstrap pareado) mostrar ganho real nas métricas de rigor.

## 5. Baixar o adaptador

O `scripts/baixar_dados.sh` já inclui `outputs/` na lista — depois do treino, ele traz o adaptador
junto com o dataset.

## Notas

- **Exemplos com uso de ferramenta:** o SFTTrainer aplica o chat template do tokenizer sobre a
  coluna `messages`; o do Qwen 3 renderiza `tool_calls`. Confirme na primeira execução real que os
  turnos de ferramenta estão sendo tokenizados como esperado.
- **Primeira execução é validação:** o `train.py` segue a receita padrão (peft + trl), mas só foi
  exercitado de verdade na GPU — trate o primeiro treino como um teste (poucas épocas, olhar a loss).
