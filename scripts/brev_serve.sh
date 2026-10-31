#!/usr/bin/env bash
# Sobe a linha de base (LLM + vLLM) na instância Brev (NVIDIA L4, 24 GB).
# Cole/execute DENTRO da instância, não no seu computador. Uso:
#   bash brev_serve.sh                 # Qwen/Qwen3-8B (padrão)
#   bash brev_serve.sh Qwen/Qwen3-4B   # modelo menor, mais folga de VRAM
#
# O servidor escuta só em 127.0.0.1: o acesso é pelo túnel SSH (ver docs/llm-base-brev.md).
# NUNCA abra a porta 8000 para a internet.
set -euo pipefail

MODEL="${1:-Qwen/Qwen3-8B}"
MAX_LEN="${VLLM_MAX_MODEL_LEN:-16384}"
PORT="${VLLM_PORT:-8000}"

# A VM do Brev tem o driver NVIDIA mas não o CUDA toolkit (nvcc). O amostrador FlashInfer
# compila um kernel em JIT no warmup e falha sem nvcc; desligamos por padrão (cai no amostrador
# nativo do PyTorch, que não precisa de nvcc). Exporte =1 para forçar o FlashInfer, se instalar
# o toolkit depois.
export VLLM_USE_FLASHINFER_SAMPLER="${VLLM_USE_FLASHINFER_SAMPLER:-0}"

python3.11 -m venv ~/vllm
source ~/vllm/bin/activate
pip install --upgrade pip
pip install "vllm>=0.9.0"

# Chave que protege o servidor. Gerada uma vez e guardada em ~/vllm_api_key.txt;
# copie-a para o seu computador (variável ECOFISIO_LLM_KEY).
KEY_FILE="$HOME/vllm_api_key.txt"
if [[ ! -s "$KEY_FILE" ]]; then
  python -c "import secrets; print(secrets.token_urlsafe(32))" > "$KEY_FILE"
fi
VLLM_API_KEY="$(cat "$KEY_FILE")"

echo "============================================================"
echo "Modelo:        $MODEL"
echo "Contexto máx.: $MAX_LEN tokens   (reduza com VLLM_MAX_MODEL_LEN=8192 se faltar VRAM)"
echo "ECOFISIO_LLM_KEY (copie para o seu computador):"
echo "    $VLLM_API_KEY"
echo "A primeira execução baixa os pesos do Hugging Face (~16 GB no 8B)."
echo "============================================================"

exec vllm serve "$MODEL" \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --max-model-len "$MAX_LEN" --gpu-memory-utilization 0.90 \
  --host 127.0.0.1 --port "$PORT" --api-key "$VLLM_API_KEY"
