"""Treino QLoRA propriamente dito (transformers + peft + trl). Precisa de GPU.

As dependências pesadas (torch, transformers, peft, trl, bitsandbytes) são importadas DENTRO da
função, para o resto do módulo (config, custo, CLI de estimativa) funcionar sem GPU e sem elas.
Instale com: pip install -e ".[train]".

Receita padrão de SFT conversacional: o SFTTrainer aplica o chat template do tokenizer sobre a
coluna "messages", então os exemplos com chamada de ferramenta dependem de o template do modelo
renderizar tool_calls (o do Qwen 3 renderiza). Confirme isso na primeira execução real.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ecofisio.training.config import TrainConfig


def treinar(cfg: TrainConfig, exemplos: list[dict[str, Any]]) -> str:
    """Ajusta o modelo com QLoRA e salva o adaptador em cfg.saida. Devolve o caminho de saída."""
    import torch
    from datasets import Dataset
    from peft import LoraConfig, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    tok = AutoTokenizer.from_pretrained(cfg.modelo_base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    quant = None
    if cfg.quatro_bits:
        quant = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )

    model = AutoModelForCausalLM.from_pretrained(
        cfg.modelo_base,
        quantization_config=quant,
        torch_dtype=torch.bfloat16,
        device_map="auto",
    )
    if cfg.quatro_bits:
        model = prepare_model_for_kbit_training(model)

    lora = LoraConfig(
        r=cfg.r,
        lora_alpha=cfg.alpha,
        lora_dropout=cfg.dropout,
        target_modules=list(cfg.alvos),
        bias="none",
        task_type="CAUSAL_LM",
    )

    ds = Dataset.from_list([{"messages": e["messages"]} for e in exemplos])

    # Resiliente a versão do TRL: passa só os argumentos que o SFTConfig instalado aceita.
    # (versões diferentes renomeiam/removem campos, ex.: max_seq_length -> max_length.)
    desejado = {
        "output_dir": cfg.saida,
        "num_train_epochs": cfg.epocas,
        "per_device_train_batch_size": cfg.batch,
        "gradient_accumulation_steps": cfg.acumulo,
        "learning_rate": cfg.lr,
        "warmup_ratio": cfg.warmup,
        "max_length": cfg.max_tokens,  # TRL recente
        "max_seq_length": cfg.max_tokens,  # TRL antigo
        "bf16": True,
        "logging_steps": 5,
        "save_strategy": "epoch",
        "seed": cfg.seed,
        "report_to": [],
    }
    try:
        from dataclasses import fields as _fields

        aceitos = {f.name for f in _fields(SFTConfig)}
    except TypeError:
        import inspect

        aceitos = set(inspect.signature(SFTConfig).parameters)
    args = SFTConfig(**{k: v for k, v in desejado.items() if k in aceitos})

    # processing_class (TRL recente) ou tokenizer (TRL antigo)
    kwargs: dict[str, Any] = {
        "model": model,
        "args": args,
        "train_dataset": ds,
        "peft_config": lora,
    }
    import inspect as _inspect

    if "processing_class" in _inspect.signature(SFTTrainer).parameters:
        kwargs["processing_class"] = tok
    else:
        kwargs["tokenizer"] = tok
    trainer = SFTTrainer(**kwargs)
    trainer.train()
    Path(cfg.saida).mkdir(parents=True, exist_ok=True)
    trainer.save_model(cfg.saida)
    tok.save_pretrained(cfg.saida)
    return cfg.saida
