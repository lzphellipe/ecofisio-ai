# LLM base no Brev (NVIDIA L4)

Linha de base da fase 1: Qwen 3 8B sem ajuste, servido pelo vLLM, respondendo com a busca na literatura. É a referência que o modelo ajustado da fase 3 precisa superar. O assistente é generalista em biologia, então as primeiras perguntas e o benchmark devem variar de área e de nível, não só a parte vegetal que já tem corpus.

**Custo (confira antes de ligar).** L4 ligada ~US$0,85–0,90/h; uma sessão de 2–3 h (subir + baixar pesos + algumas avaliações) sai por ~US$2–3. Disco de 100 GB é cobrado mesmo parada (~US$0,17/GB·mês no SSD do GCP ≈ US$17/mês se deixar). Pare a instância ao fim; se não for usar por semanas, apague-a (o modelo rebaixa em minutos).

## Instância

| Item | Valor | Observação |
| --- | --- | --- |
| GPU | 1× L4, 24 GB | Qwen 3 8B em BF16 ocupa ~16 GB; sobram ~5 GB para o cache de contexto |
| Tipo | g2-standard-4 (GCP), 16 GB RAM, 4 CPUs | suficiente para servir |
| Disco | **100 GB** | 256 GB é sobra: o modelo ocupa ~16 GB. O disco é cobrado mesmo com a instância parada |
| Software | Modo VM com Jupyter | vLLM instalado por pip |
| Custo | ~US$ 0,85/h ligada + armazenamento | uma sessão de testes de 2–3 h custa ~US$ 2–3 |

**Pare a instância ao fim de cada sessão.** Parada, ela só cobra o disco. Se não for usar por semanas, apague a instância: o modelo baixa de novo em minutos.

## 0. Ao criar a instância: modo e script de configuração

Escolha **Modo VM** (inclui Python, CUDA e Docker, dá shell completo e disco persistente — é o que estes scripts assumem). Jupyter é opcional: ligue se for usar notebooks, senão deixe desligado (o acesso é por SSH).

No campo **"Script de Configuração"**, cole o conteúdo de [`scripts/brev_setup.sh`](../scripts/brev_setup.sh). Ele roda uma vez quando a VM fica pronta e deixa o ambiente instalado (deps, repo em `/opt/ecofisio-ai`, venv e vLLM). Ele **não** sobe o servidor nem treina — isso você dispara depois por SSH. Se o repositório for privado, o clone falha e o script segue só com o venv; nesse caso suba o código manualmente ou use um token de deploy.

## 1. Na instância: subir o servidor

Copie `scripts/brev_serve.sh` para a instância (ou cole o conteúdo) e rode:

```bash
bash brev_serve.sh                 # Qwen/Qwen3-8B (padrão)
# bash brev_serve.sh Qwen/Qwen3-4B # modelo menor, se faltar VRAM
```

O script cria o venv, instala o vLLM, gera uma vez a chave do servidor (guardada em `~/vllm_api_key.txt`) e sobe o `vllm serve`. Ele imprime a chave: **copie-a para o seu computador** (vira `ECOFISIO_LLM_KEY`). Detalhes:

- `--enable-auto-tool-choice --tool-call-parser hermes`: chamada de ferramentas do Qwen 3, como na [documentação do Qwen para vLLM](https://qwen.readthedocs.io/en/v3.0/deployment/vllm.html).
- Contexto `16384`: estimativa a confirmar. Qwen 3 8B usa ~0,14 MB de cache por token, então ~5 GB livres comportam ~35 mil tokens. Se o vLLM reclamar de memória, rode com `VLLM_MAX_MODEL_LEN=8192 bash brev_serve.sh`.
- `--host 127.0.0.1`: o servidor só escuta dentro da instância. **Não abra a porta 8000 para a internet**; o acesso é pelo túnel SSH abaixo.

A primeira execução baixa ~16 GB de pesos do Hugging Face.

## 2. No seu computador: túnel e pergunta

Em um terminal, abra o túnel (use o host SSH que o Brev mostra para a instância):

```powershell
ssh -N -L 8000:localhost:8000 <host-ssh-da-instancia>
```

Em outro terminal, na pasta do repositório:

```powershell
$env:ECOFISIO_LLM_KEY = "<a chave gerada no passo 1>"
ecofisio-ask "Qual o efeito da seca sobre a condutância estomática e o Vcmax?" `
  --crossref-email luizfelipealveslopes9@gmail.com --sem-verificacao-semantica
```

- `--sem-verificacao-semantica` só enquanto não houver modelo NLI escolhido: as afirmações saem com aviso de que o trecho não foi conferido semanticamente. Sem essa opção, toda afirmação citada é bloqueada, como manda a regra do projeto.
- Cada pergunta grava o rastro completo em `runs/<data>.json`.
- `--pensar` liga o modo de raciocínio do Qwen 3: respostas mais lentas, possivelmente melhores. Vale comparar os dois no benchmark.

## 3. O que observar nas primeiras perguntas

- O modelo chama a busca antes de responder? Faz consultas em inglês?
- Quantas afirmações são bloqueadas e por quê: ID inexistente indica que o modelo inventou citação; "consenso exige 2 DOIs" indica força da evidência exagerada.
- O resumo diz algo que nenhuma afirmação verificada sustenta?

Essas observações viram os primeiros itens do benchmark da fase 2.
