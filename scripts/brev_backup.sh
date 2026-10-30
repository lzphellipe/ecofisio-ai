#!/usr/bin/env bash
# Backup dos artefatos do projeto na instância Brev ANTES de apagá-la.
# Rode DENTRO da instância, na pasta do repositório (ou passe o caminho como 1º argumento).
#
# NÃO é necessário se você só for PARAR (stop) a instância: o disco persiste e tudo continua lá
# ao religar. Use isto quando for APAGAR a instância (para não pagar o disco) e ainda assim
# quiser guardar os artefatos para retomar os treinos numa instância nova.
#
# O que entra no backup (o resto rebaixa/reinstala sozinho):
#   data/sft        dataset de treino gerado
#   data/processed  corpus e índice
#   data/raw        cache bruto imutável do Europe PMC (re-baixável, mas incluído por ser imutável)
#   runs            rastros de perguntas e avaliações
#   outputs adapters checkpoints   saídas de treino (QLoRA), quando existirem
# Fora do backup: venv, caches de pip e de modelos (~/.cache/huggingface, ~16 GB, rebaixam em
# minutos) e __pycache__.
set -euo pipefail

REPO="${1:-$PWD}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$HOME/ecofisio-backup-$STAMP.tgz"

cd "$REPO"
PATHS=()
for p in data/sft data/processed data/raw runs outputs adapters checkpoints; do
  [[ -e "$p" ]] && PATHS+=("$p")
done
if [[ ${#PATHS[@]} -eq 0 ]]; then
  echo "nada a salvar em $REPO (procurei data/, runs/, outputs/, adapters/, checkpoints/)" >&2
  exit 1
fi

tar --exclude='__pycache__' -czf "$OUT" "${PATHS[@]}"
sha256sum "$OUT" | tee "$OUT.sha256"
echo "backup: $OUT ($(du -h "$OUT" | cut -f1))  — conteúdo: ${PATHS[*]}"
echo
echo "Puxe para o seu computador (rode NO SEU computador; troque pelo host SSH do Brev):"
echo "  rsync -avP <host-ssh-do-brev>:$OUT ."
echo "  rsync -avP <host-ssh-do-brev>:$OUT.sha256 ."
echo "  sha256sum -c $(basename "$OUT").sha256   # confere a integridade"
echo
echo "Ou para um bucket na nuvem (precisa da sua conta/credenciais na instância):"
echo "  gsutil cp $OUT $OUT.sha256 gs://SEU-BUCKET/ecofisio/"
echo "Adaptadores QLoRA também podem ir para o Hugging Face Hub (huggingface-cli upload)."
