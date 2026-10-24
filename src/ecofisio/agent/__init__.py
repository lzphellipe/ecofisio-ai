"""Agente de pesquisa: LLM orquestrando ferramentas, com auditoria de evidência na saída."""

from ecofisio.agent.llm import ChatModel, ChatReply, LLMError, OpenAICompatibleChat, ToolCall
from ecofisio.agent.research import (
    SYSTEM_PROMPT,
    AgentError,
    BlockedClaim,
    ResearchAgent,
    ResearchAnswer,
    parse_final_json,
    render_text,
)
from ecofisio.agent.tools import SEARCH_TOOL, PassageRegistry, SearchTool

__all__ = [
    "SEARCH_TOOL",
    "SYSTEM_PROMPT",
    "AgentError",
    "BlockedClaim",
    "ChatModel",
    "ChatReply",
    "LLMError",
    "OpenAICompatibleChat",
    "PassageRegistry",
    "ResearchAgent",
    "ResearchAnswer",
    "SearchTool",
    "ToolCall",
    "parse_final_json",
    "render_text",
]
