#!/usr/bin/env bash
# Script de Configuração do Brev (Modo VM) para o projeto ecofisio-ai.
# Cole o conteúdo no campo "Script de Configuração". Roda UMA vez, quando a VM fica pronta.
#
# O que faz: instala dependências, clona o repo, cria o venv e instala o projeto (compila o
# kernel C++) + vLLM. O que NÃO faz: subir o servidor ou treinar — isso você dispara por SSH
# depois (bash scripts/brev_serve.sh), para o provisionamento encerrar sem travar.
#
# Variáveis opcionais (defina no ambiente do script, se quiser mudar):
#   ECOFISIO_REPO_URL  (padrão: https://github.com/lzphellipe/ecofisio-ai.git)
#   ECOFISIO_BRANCH    (padrão: main)
#   ECOFISIO_DIR       (padrão: /opt/ecofisio-ai)
#   ECOFISIO_USER      (usuário de login da VM; padrão: ubuntu)
#   ECOFISIO_PREFETCH  (ex.: Qwen/Qwen3-8B para pré-baixar os pesos; padrão: não baixa)
set -euo pipefail

REPO_URL="${ECOFISIO_REPO_URL:-https://github.com/lzphellipe/ecofisio-ai.git}"
BRANCH="${ECOFISIO_BRANCH:-main}"
DEST="${ECOFISIO_DIR:-/opt/ecofisio-ai}"
LOGIN_USER="${ECOFISIO_USER:-ubuntu}"

log() { echo "[ecofisio-setup] $*"; }
SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"

log "instalando dependências de sistema (inclui Python 3.11; o projeto exige >= 3.11)"
export DEBIAN_FRONTEND=noninteractive
$SUDO apt-get update -y
$SUDO apt-get install -y software-properties-common
$SUDO add-apt-repository -y ppa:deadsnakes/ppa
$SUDO apt-get update -y
$SUDO apt-get install -y git build-essential python3.11 python3.11-venv python3.11-dev python3-pip

log "preparando $DEST"
$SUDO mkdir -p "$DEST"
$SUDO chown "$(id -un):$(id -gn)" "$DEST"

if [[ ! -d "$DEST/.git" ]]; then
  if git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$DEST" 2>/dev/null; then
    log "repo clonado"
  else
    log "não consegui clonar $REPO_URL (repo privado?). Suba o código em $DEST e rode este"
    log "script de novo, ou instale à mão. Seguindo só com o venv + vLLM."
  fi
else
  log "repo já existe; atualizando"
  git -C "$DEST" pull --ff-only || true
fi

log "criando venv com Python 3.11 (cmake/ninja via pip garantem cmake >= 3.26 para o kernel)"
python3.11 -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install --upgrade pip
"$DEST/.venv/bin/pip" install "cmake>=3.26" ninja
if [[ -f "$DEST/pyproject.toml" ]]; then
  "$DEST/.venv/bin/pip" install -e "$DEST[dev]"
fi
"$DEST/.venv/bin/pip" install "vllm>=0.9.0"

# pré-download opcional dos pesos (16 GB no 8B); poupa tempo no primeiro serve/treino
if [[ -n "${ECOFISIO_PREFETCH:-}" ]]; then
  log "pré-baixando pesos: $ECOFISIO_PREFETCH"
  "$DEST/.venv/bin/pip" install -U "huggingface_hub[cli]"
  "$DEST/.venv/bin/huggingface-cli" download "$ECOFISIO_PREFETCH" || log "pré-download falhou (segue)"
fi

# devolve a posse ao usuário de login e ativa o venv no shell interativo
if id "$LOGIN_USER" &>/dev/null; then
  $SUDO chown -R "$LOGIN_USER:$LOGIN_USER" "$DEST"
  PROFILE="/home/$LOGIN_USER/.bashrc"
  if [[ -f "$PROFILE" ]] && ! grep -q "ecofisio-ai/.venv" "$PROFILE"; then
    echo "source $DEST/.venv/bin/activate && cd $DEST" | $SUDO tee -a "$PROFILE" >/dev/null
  fi
fi

log "pronto. Entre por SSH e rode: cd $DEST && bash scripts/brev_serve.sh"
