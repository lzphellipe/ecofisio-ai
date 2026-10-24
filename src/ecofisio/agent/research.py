"""Agente de pesquisa base: LLM + busca na literatura + auditoria de cada afirmação.

Esta é a linha de base "modelo base + RAG" que o modelo ajustado da fase 3 precisa superar.

Fluxo: pergunta → o modelo chama `buscar_literatura` quantas vezes precisar → responde em JSON
com afirmações que citam IDs de trechos → cada afirmação vira `Claim` (com o texto real do trecho)
→ auditoria (retratação + sustentação semântica) → só o que passa é entregue; o resto volta
marcado como bloqueado, com o motivo.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ecofisio.agent.llm import ChatModel
from ecofisio.agent.tools import SEARCH_TOOL, PassageRegistry, SearchTool
from ecofisio.evidence.audit import AuditReport, audit_claim
from ecofisio.evidence.models import Claim, EpistemicStatus, EvidenceStrength
from ecofisio.evidence.retraction import RetractionChecker
from ecofisio.evidence.verify import SupportVerifier
from ecofisio.rag.index import LiteratureIndex

SYSTEM_PROMPT = """Você é um assistente de pesquisa em ecofisiologia e bioquímica vegetal, para \
pesquisadores de mestrado e doutorado. Rigor vale mais que completude.

Regras:
1. Antes de afirmar qualquer fato, use a ferramenta buscar_literatura (consultas em inglês). \
Faça mais de uma busca se a primeira não cobrir a pergunta.
2. Só afirme o que os trechos encontrados sustentam. Não use conhecimento próprio sem citação; \
se precisar, marque a afirmação como "especulacao".
3. Cite apenas IDs de trechos devolvidos pela busca (T1, T2, ...). Nunca invente IDs, DOIs ou \
números.
4. Força da evidência: "consenso" só com 2 ou mais artigos diferentes concordando; \
"resultado_isolado" para um estudo; "controverso" quando os trechos discordam (cite os dois \
lados); "especulacao" para hipóteses sem sustentação direta.
5. Status: "medido" quando o estudo citado mediu aquilo; "inferido" quando é interpretação. \
Trechos com primary_evidence=false (editorial, revisão, comentário) não sustentam "medido".
6. Se a literatura encontrada não responde a pergunta, diga isso em "lacunas". Responder \
"não encontrei evidência" é uma resposta correta.

Quando terminar de buscar, responda SOMENTE com um JSON neste formato, em português:
{"resumo": "2 a 4 frases respondendo a pergunta",
 "afirmacoes": [{"texto": "...", "forca": "consenso|resultado_isolado|controverso|especulacao",
                 "status": "medido|inferido", "citacoes": ["T1", "T3"]}],
 "lacunas": ["o que a literatura encontrada não responde"]}"""

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class AgentError(RuntimeError):
    pass


def _norm(value: Any) -> str:
    s = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[\s\-]+", "_", s.strip())


def parse_final_json(text: str) -> dict[str, Any]:
    """Extrai o JSON final mesmo com bloco <think>, cercas ``` ou texto em volta."""
    body = _THINK.sub("", text).strip()
    if m := _FENCE.search(body):
        body = m.group(1)
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("nenhum objeto JSON na resposta")
    data = json.loads(body[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON final não é um objeto")
    return data


@dataclass(slots=True)
class BlockedClaim:
    text: str
    reasons: list[str]
    raw: dict[str, Any]


@dataclass(slots=True)
class ResearchAnswer:
    question: str
    model: str
    summary: str
    delivered: list[AuditReport] = field(default_factory=list)
    blocked: list[BlockedClaim] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    searches: list[str] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        def claim_d(rep: AuditReport) -> dict[str, Any]:
            c = rep.claim
            return {
                "texto": c.text,
                "forca": str(c.strength),
                "status": str(c.status),
                "citacoes": [
                    {"doi": x.doi, "secao": x.page, "trecho": x.passage} for x in c.citations
                ],
                "avisos": rep.warnings,
                "verificacao_semantica": rep.semantic_check,
            }

        return {
            "pergunta": self.question,
            "modelo": self.model,
            "criado_em": self.created_at,
            "resumo": self.summary,
            "entregues": [claim_d(r) for r in self.delivered],
            "bloqueadas": [{"texto": b.text, "motivos": b.reasons} for b in self.blocked],
            "lacunas": self.gaps,
            "buscas": self.searches,
            "transcricao": self.transcript,
        }


class ResearchAgent:
    def __init__(
        self,
        model: ChatModel,
        index: LiteratureIndex,
        checker: RetractionChecker,
        verifier: SupportVerifier | None = None,
        *,
        require_semantic: bool = True,
        max_steps: int = 6,
        max_repairs: int = 1,
    ) -> None:
        self.model, self.index, self.checker, self.verifier = model, index, checker, verifier
        self.require_semantic = require_semantic
        self.max_steps, self.max_repairs = max_steps, max_repairs

    def ask(self, question: str) -> ResearchAnswer:
        if not question.strip():
            raise ValueError("pergunta vazia")
        registry = PassageRegistry()
        search = SearchTool(self.index, registry)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        searches: list[str] = []
        repairs = 0
        final: dict[str, Any] | None = None

        for step in range(self.max_steps + self.max_repairs + 1):
            out_of_steps = step >= self.max_steps
            if out_of_steps:
                messages.append(
                    {
                        "role": "user",
                        "content": "Limite de buscas atingido. Responda agora só com o JSON final.",
                    }
                )
            reply = self.model.chat(messages, tools=None if out_of_steps else [SEARCH_TOOL])
            messages.append(reply.as_message())

            if reply.tool_calls and not out_of_steps:
                for tc in reply.tool_calls:
                    if tc.name == SEARCH_TOOL["function"]["name"]:
                        result = search(tc.arguments)
                        searches.append(str(tc.arguments.get("consulta", "")))
                    else:
                        result = json.dumps({"erro": f"ferramenta desconhecida: {tc.name}"})
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                continue

            try:
                final = parse_final_json(reply.content)
                break
            except (ValueError, json.JSONDecodeError) as exc:
                if repairs >= self.max_repairs:
                    raise AgentError(f"o modelo não devolveu o JSON final: {exc}") from exc
                repairs += 1
                messages.append(
                    {
                        "role": "user",
                        "content": "Sua resposta não é um JSON válido. Responda só com o JSON.",
                    }
                )
        if final is None:
            raise AgentError("o modelo não concluiu a resposta dentro do limite de passos")

        answer = ResearchAnswer(
            question=question,
            model=self.model.name,
            summary=str(final.get("resumo") or "").strip(),
            gaps=[str(g) for g in final.get("lacunas") or [] if str(g).strip()],
            searches=searches,
            transcript=messages,
        )
        for raw in final.get("afirmacoes") or []:
            self._judge(raw if isinstance(raw, dict) else {"texto": str(raw)}, registry, answer)
        return answer

    def _judge(self, raw: dict[str, Any], reg: PassageRegistry, answer: ResearchAnswer) -> None:
        text = str(raw.get("texto") or "").strip()
        reasons: list[str] = []
        try:
            strength = EvidenceStrength(_norm(raw.get("forca", "")))
        except ValueError:
            reasons.append(f"força da evidência inválida: {raw.get('forca')!r}")
        try:
            status = EpistemicStatus(_norm(raw.get("status", "")))
        except ValueError:
            reasons.append(f"status inválido: {raw.get('status')!r}")

        citations, cited = [], []
        for pid in raw.get("citacoes") or []:
            pid = str(pid).strip().upper()
            if pid not in reg.by_id:
                reasons.append(f"{pid}: trecho inexistente (não foi devolvido pela busca)")
                continue
            try:
                citations.append(reg.citation(pid))
                cited.append(reg.by_id[pid])
            except ValueError as exc:
                reasons.append(str(exc))
        if reasons:
            answer.blocked.append(BlockedClaim(text, reasons, raw))
            return
        try:
            claim = Claim(text, strength, status, citations)
        except ValueError as exc:
            answer.blocked.append(BlockedClaim(text, [str(exc)], raw))
            return

        report = audit_claim(
            claim, self.checker, self.verifier, require_semantic=self.require_semantic
        )
        if (
            status is EpistemicStatus.MEDIDO
            and cited
            and not any(p.primary_evidence for p in cited)
        ):
            tipos = sorted({p.article_type or "desconhecido" for p in cited})
            report.warnings.append(
                f"marcada como medida, mas só cita fontes não primárias ({', '.join(tipos)})"
            )
        if report.blocked:
            answer.blocked.append(BlockedClaim(text, report.problems, raw))
        else:
            answer.delivered.append(report)


def render_text(ans: ResearchAnswer) -> str:
    """Saída legível para o terminal."""
    out = [f"Pergunta: {ans.question}", f"Modelo: {ans.model}", ""]
    out += [ans.summary or "(sem resumo)", ""]
    if ans.delivered:
        out.append(f"Afirmações verificadas ({len(ans.delivered)}):")
        for i, rep in enumerate(ans.delivered, 1):
            c = rep.claim
            out.append(f"  {i}. {c.text}  [{c.strength}, {c.status}]")
            for cit in c.citations:
                out.append(f"     doi:{cit.doi} · {cit.page}")
            out += [f"     aviso: {w}" for w in rep.warnings]
    if ans.blocked:
        out.append(f"\nAfirmações bloqueadas ({len(ans.blocked)}), não usar sem conferir:")
        for b in ans.blocked:
            out.append(f"  - {b.text}")
            out += [f"     motivo: {r}" for r in b.reasons]
    if ans.gaps:
        out.append("\nLacunas:")
        out += [f"  - {g}" for g in ans.gaps]
    out.append(f"\nBuscas feitas: {'; '.join(ans.searches) or 'nenhuma'}")
    return "\n".join(out)
