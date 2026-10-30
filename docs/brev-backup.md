# Guardar os artefatos do Brev entre sessões

## Parar ≠ apagar

- **Parar (stop):** o disco persiste. Tudo (dataset, índice, checkpoints) continua lá ao religar.
  Você não precisa copiar nada; paga só o disco (~R$92/mês pelos 100 GB). É o caminho mais simples
  entre um treino e outro.
- **Apagar (delete):** o disco some junto. Só faça isto para parar de pagar o disco — e, antes,
  guarde os artefatos com o backup abaixo, para retomar numa instância nova.

## Backup antes de apagar

Na instância, na pasta do repositório:

```bash
bash scripts/brev_backup.sh
```

Gera `~/ecofisio-backup-<data>.tgz` (+ `.sha256`) com `data/sft`, `data/processed`, `data/raw`,
`runs` e as saídas de treino (`outputs/`, `adapters/`, `checkpoints/`) que existirem. Ficam de
fora o venv e os caches de pip e de modelos (`~/.cache/huggingface`, ~16 GB), que rebaixam/
reinstalam sozinhos. O script imprime o comando `rsync` para puxar o arquivo.

No seu computador:

```powershell
rsync -avP <host-ssh-do-brev>:~/ecofisio-backup-<data>.tgz .
rsync -avP <host-ssh-do-brev>:~/ecofisio-backup-<data>.tgz.sha256 .
sha256sum -c ecofisio-backup-<data>.tgz.sha256
```

(Alternativa: `gsutil cp` para um bucket seu, ou os adaptadores QLoRA no Hugging Face Hub.)

## Restaurar numa instância nova

Envie o `.tgz` para a nova instância e restaure na pasta do repositório:

```bash
rsync -avP ecofisio-backup-<data>.tgz ecofisio-backup-<data>.tgz.sha256 <host-ssh-novo>:~/
# na nova instância, na pasta do repo:
bash scripts/brev_restore.sh ~/ecofisio-backup-<data>.tgz
```

Os pesos do modelo rebaixam no primeiro `vllm serve` ou no treino.

## Observação sobre versionamento

`data/` está fora do git (ver `.gitignore`). Para versionar o dataset e o índice a longo prazo, o
caminho do projeto é o DVC com um remoto (ex.: bucket no GCS): aí cada versão do dataset fica
rastreada junto ao commit que a gerou, e o backup manual acima vira só a cópia de segurança.
