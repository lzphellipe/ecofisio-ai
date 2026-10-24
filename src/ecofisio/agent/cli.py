"""Pergunta ao assistente pela linha de comando.

    ecofisio-ask "Qual o efeito da seca sobre o Vcmax?" --base-url http://localhost:8000/v1

O modelo roda num servidor compatível com a API da OpenAI (ex.: vLLM na GPU alugada, acessado
por túnel SSH). Cada execução salva o rastro completo em JSON (pergunta, buscas, mensagens,
afirmações entregues e bloqueadas): é material para o benchmark e para auditar respostas.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from ecofisio.agent.llm import LLMError, OpenAICompatibleChat
from ecofisio.agent.research import AgentError, ResearchAgent, render_text
from ecofisio.evidence.retraction import CrossrefClient, RetractionChecker, RetractionWatchIndex
from ecofisio.rag.index import LiteratureIndex


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("pergunta")
    ap.add_argument(
        "--base-url", default=os.environ.get("ECOFISIO_LLM_URL", "http://localhost:8000/v1")
    )
    ap.add_argument("--model", default=os.environ.get("ECOFISIO_LLM_MODEL", "Qwen/Qwen3-8B"))
    ap.add_argument(
        "--api-key-env",
        default="ECOFISIO_LLM_KEY",
        help="variável de ambiente com a chave do servidor (a chave nunca vai na linha de comando)",
    )
    ap.add_argument("--index", type=Path, default=Path("data/processed/literature"))
    ap.add_argument("--rw-csv", type=Path, default=None, help="CSV do Retraction Watch (offline)")
    ap.add_argument("--crossref-email", default=None, help="contato para a API da Crossref")
    ap.add_argument("--nli-model", default=None, help="modelo NLI do verificador semântico")
    ap.add_argument(
        "--sem-verificacao-semantica",
        action="store_true",
        help="entrega afirmações sem verificação semântica, marcadas com aviso (só para testes)",
    )
    ap.add_argument("--pensar", action="store_true", help="liga o modo de raciocínio do Qwen 3")
    ap.add_argument("--max-passos", type=int, default=6)
    ap.add_argument("--rastro", type=Path, default=Path("runs"), help="pasta dos rastros JSON")
    ap.add_argument("--json", action="store_true", help="imprime o resultado em JSON")
    args = ap.parse_args(argv)

    if args.rw_csv is None and args.crossref_email is None:
        ap.error(
            "informe --rw-csv e/ou --crossref-email: sem checagem de retratação, nada é entregue"
        )
    index = LiteratureIndex.load(args.index)
    checker = RetractionChecker(
        index=RetractionWatchIndex.from_csv(args.rw_csv) if args.rw_csv else None,
        client=CrossrefClient(mailto=args.crossref_email) if args.crossref_email else None,
    )
    verifier = None
    if args.nli_model:
        from ecofisio.evidence.verify import NLIVerifier

        verifier = NLIVerifier(args.nli_model)

    model = OpenAICompatibleChat(
        args.base_url,
        args.model,
        api_key=os.environ.get(args.api_key_env),
        extra_body={"chat_template_kwargs": {"enable_thinking": args.pensar}},
    )
    agent = ResearchAgent(
        model,
        index,
        checker,
        verifier,
        require_semantic=not args.sem_verificacao_semantica,
        max_steps=args.max_passos,
    )
    try:
        answer = agent.ask(args.pergunta)
    except (LLMError, AgentError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    finally:
        model.close()

    args.rastro.mkdir(parents=True, exist_ok=True)
    trace = args.rastro / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    trace.write_text(json.dumps(answer.to_dict(), ensure_ascii=False, indent=2), "utf-8")
    if args.json:
        print(json.dumps(answer.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_text(answer))
        print(f"\nRastro completo: {trace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
