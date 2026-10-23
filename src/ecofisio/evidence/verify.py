"""Verificação semântica: o trecho citado sustenta a afirmação?

Usa inferência de linguagem natural (NLI): premissa = trecho do artigo, hipótese = afirmação.
Limitações que precisam constar em qualquer relato de resultado:
- Modelos NLI são treinados em texto geral; em texto técnico de fisiologia vegetal a precisão
  precisa ser MEDIDA num conjunto anotado por especialistas antes de confiar nos números.
- Afirmação em português e trecho em inglês exigem modelo multilíngue (cross-lingual NLI).
- NLI avalia um par trecho/afirmação; não julga se a afirmação é uma boa síntese da literatura.

O modelo não tem padrão no código de propósito: escolha um, valide no seu conjunto anotado e
registre o nome no relatório. Candidatos a avaliar (confira o model card e a licença no Hugging
Face antes de usar): cross-encoders NLI baseados em DeBERTa-v3 e modelos mDeBERTa multilíngues
ajustados em XNLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class SupportLabel(StrEnum):
    SUSTENTA = "sustenta"
    CONTRADIZ = "contradiz"
    NAO_SUSTENTA = "nao_sustenta"  # neutro: o trecho não diz isso


@dataclass(frozen=True, slots=True)
class VerificationResult:
    label: SupportLabel
    entailment: float
    contradiction: float
    model: str


class SupportVerifier(Protocol):
    name: str

    def verify(self, claim: str, passage: str) -> VerificationResult: ...


def label_indices(id2label: dict[int, str]) -> dict[str, int]:
    """Mapeia rótulos do modelo para 'entailment'/'neutral'/'contradiction' pelo nome.

    Lê do config do modelo em vez de supor a ordem: modelos diferentes ordenam diferente.
    """
    out: dict[str, int] = {}
    for i, raw in id2label.items():
        name = raw.lower()
        if name.startswith("not_entail") or name.startswith("non_entail"):
            out["not_entailment"] = int(i)
        elif "entail" in name:
            out["entailment"] = int(i)
        elif "contradict" in name:
            out["contradiction"] = int(i)
        elif "neutral" in name:
            out["neutral"] = int(i)
    if "entailment" not in out:
        raise ValueError(f"o modelo não expõe rótulo de entailment: {id2label}")
    return out


def decide(
    entailment: float, contradiction: float, *, min_entailment: float, min_contradiction: float
) -> SupportLabel:
    if entailment >= min_entailment:
        return SupportLabel.SUSTENTA
    if contradiction >= min_contradiction:
        return SupportLabel.CONTRADIZ
    return SupportLabel.NAO_SUSTENTA


class NLIVerifier:
    """Verificador com um modelo de classificação NLI do Hugging Face (extra `nli`)."""

    def __init__(
        self,
        model_name: str,
        *,
        min_entailment: float = 0.5,
        min_contradiction: float = 0.5,
        device: str | None = None,
        max_length: int = 512,
    ) -> None:
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:  # pragma: no cover - depende do extra instalado
            raise ImportError("instale o extra: pip install -e '.[nli]'") from exc
        self.name = model_name
        self._torch = torch
        self._tok = AutoTokenizer.from_pretrained(model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(model_name).eval()
        if device:
            self._model.to(device)
        self._device = device
        self._idx = label_indices(self._model.config.id2label)
        self._min_e, self._min_c, self._max_len = min_entailment, min_contradiction, max_length

    def verify(self, claim: str, passage: str) -> VerificationResult:
        enc = self._tok(
            passage, claim, truncation="only_first", max_length=self._max_len, return_tensors="pt"
        )
        if self._device:
            enc = {k: v.to(self._device) for k, v in enc.items()}
        with self._torch.no_grad():
            probs = self._torch.softmax(self._model(**enc).logits[0], dim=-1).tolist()
        e = probs[self._idx["entailment"]]
        c = probs[self._idx["contradiction"]] if "contradiction" in self._idx else 0.0
        label = decide(e, c, min_entailment=self._min_e, min_contradiction=self._min_c)
        return VerificationResult(label=label, entailment=e, contradiction=c, model=self.name)
