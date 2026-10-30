#!/usr/bin/env bash
# Restaura o backup numa instância Brev nova, para retomar os treinos.
# Rode DENTRO da nova instância. Uso:
#   bash brev_restore.sh ~/ecofisio-backup-AAAAMMDD.tgz [REPO]
#
# Primeiro envie o .tgz do seu computador para a nova instância, por exemplo:
#   rsync -avP ecofisio-backup-AAAAMMDD.tgz ecofisio-backup-AAAAMMDD.tgz.sha256 <host-ssh-novo>:~/
set -euo pipefail

TARBALL="${1:?informe o caminho do .tgz do backup}"
REPO="${2:-$PWD}"

if [[ -f "$TARBALL.sha256" ]]; then
  (cd "$(dirname "$TARBALL")" && sha256sum -c "$(basename "$TARBALL").sha256")
else
  echo "aviso: $TARBALL.sha256 não encontrado; pulando a verificação de integridade" >&2
fi

mkdir -p "$REPO"
tar -xzf "$TARBALL" -C "$REPO"
echo "restaurado em $REPO. Conteúdo de data/:"
ls -1 "$REPO/data" 2>/dev/null || echo "  (sem pasta data/)"
echo "Os pesos do modelo rebaixam sozinhos no primeiro 'vllm serve' ou no treino."
