#!/usr/bin/env bash
# Baixa, para o seu PC, os dados gerados na VM do Brev (dataset, rastros das perguntas,
# projetos/artefatos e saídas de treino) — num comando só. Rode no SEU PC / WSL, onde o `brev`
# está logado (NÃO dentro da VM: a VM não consegue empurrar arquivos para o seu PC).
#
# Uso:
#   bash scripts/baixar_dados.sh                       # baixa da instância eco-bio-vllm
#   INSTANCIA=outra DEST=~/dados bash scripts/baixar_dados.sh
#   GERAR=1 LLM_KEY=<chave-do-vllm> bash scripts/baixar_dados.sh   # gera o dataset na VM e baixa
#
# Se o nome da instância não resolver no ssh/rsync, passe o host explícito (painel do Brev,
# seção TCP/UDP Ports, porta 22):
#   SSH_HOST=global.prd.ga.run.brev.nvidia.com SSH_PORT=24462 bash scripts/baixar_dados.sh
set -euo pipefail

INSTANCIA="${INSTANCIA:-eco-bio-vllm}"
REMOTO="${REMOTO:-/opt/ecofisio-ai}"
DEST="${DEST:-./ecofisio-dados}"
EMAIL="${EMAIL:-luizfelipealveslopes9@gmail.com}"

# Alvo SSH: host explícito (SSH_HOST/SSH_PORT) ou o nome da instância (config do brev).
if [[ -n "${SSH_HOST:-}" ]]; then
  SSH_TARGET="ubuntu@${SSH_HOST}"
  SSH_CMD=(ssh -p "${SSH_PORT:-22}")
  RSYNC_SSH=(-e "ssh -p ${SSH_PORT:-22}")
else
  SSH_TARGET="$INSTANCIA"
  SSH_CMD=(ssh)
  RSYNC_SSH=()
fi

if [[ "${GERAR:-0}" == "1" ]]; then
  : "${LLM_KEY:?defina LLM_KEY (a chave do vLLM) para gerar o dataset}"
  echo "==> Gerando o dataset na VM (o vLLM precisa estar no ar)..."
  "${SSH_CMD[@]}" "$SSH_TARGET" "cd '$REMOTO' && source .venv/bin/activate && \
    ECOFISIO_LLM_KEY='$LLM_KEY' ECOFISIO_LLM_URL=http://localhost:8000/v1 \
    ECOFISIO_LLM_MODEL=Qwen/Qwen3-8B \
    ecofisio-dataset --crossref-email '$EMAIL' --sem-verificacao-semantica --out data/sft"
fi

mkdir -p "$DEST"
# data/ já estruturado; runs e as saídas de treino (quando existirem)
for sub in data/sft data/app runs outputs adapters checkpoints; do
  if "${SSH_CMD[@]}" "$SSH_TARGET" "test -e '$REMOTO/$sub'"; then
    echo "==> baixando $sub"
    mkdir -p "$DEST/$(dirname "$sub")"
    rsync -avP "${RSYNC_SSH[@]}" "$SSH_TARGET:$REMOTO/$sub" "$DEST/$(dirname "$sub")/"
  fi
done

echo "==> Pronto. Dados em: $DEST"
