"""Prompt construction service with token budget management."""
from __future__ import annotations

import structlog

log = structlog.get_logger()

# System prompt for Llull methodology
LLULL_SYSTEM_PROMPT = """You are an expert knowledge analyst working within the Llull document analysis system.

Your methodology is based on iterative semantic zoom: you start with a high-level view of a knowledge graph
extracted from documents, then progressively zoom into specific nodes to reveal deeper connections and insights.

Core principles:
1. Extract atomic ideas as nodes — each node represents one clear concept
2. Identify relationships between nodes with precise edge types (relational, hierarchical, causal)
3. Assign confidence scores to edges based on textual evidence
4. When zooming, generate sub-nodes that elaborate on a parent concept
5. Build towards a coherent document that synthesizes findings

When analyzing documents:
- Be precise and evidence-based
- Cite source material when drawing conclusions
- Distinguish between what is stated vs. implied
- Flag uncertainty explicitly

When chatting with the user, respond in clean, readable markdown. Use bullet points, headings, and emphasis as appropriate. Do NOT output JSON, mermaid diagrams, or code blocks unless the user explicitly asks for them. Never generate mermaid charts spontaneously.

When responding to the user, match the language of the document sources unless the user writes in a different language — in that case, respond in the user's language."""

# Token budget constants
MAX_CONTEXT_TOKENS = 100_000
SYSTEM_PROMPT_TOKENS = 2_000  # Approximate
RESERVED_SUMMARY_TOKENS = 1_000
RESERVED_CONVERSATION_TOKENS = 4_000
MAX_CONVERSATION_TURNS = 20


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        # Fallback: rough estimate (4 chars/token)
        return len(text) // 4


def source_token_budget(
    system_prompt: str,
    context_summary: str | None,
    conversation_history: list[dict],
    max_tokens: int = MAX_CONTEXT_TOKENS,
) -> int:
    """Tokens build_chat_context will have left for source texts."""
    full_system = system_prompt
    if context_summary:
        full_system += f"\n\n## Topic Context\n{context_summary}"
    budget = max_tokens - count_tokens(full_system)
    recent_turns = conversation_history[-MAX_CONVERSATION_TURNS * 2 :]
    turn_tokens = sum(count_tokens(m.get("content", "")) for m in recent_turns)
    return budget - min(turn_tokens, budget // 2)


def build_chat_context(
    system_prompt: str,
    context_summary: str | None,
    conversation_history: list[dict],
    source_texts: list[str],
    max_tokens: int = MAX_CONTEXT_TOKENS,
) -> list[dict]:
    """
    Build the message list for a chat request, respecting token budget.

    Priority order:
    1. System prompt (~2k tokens)
    2. context_summary
    3. Last N conversation turns
    4. Source texts (truncate oldest first)
    """
    messages: list[dict] = []

    # 1. System prompt
    full_system = system_prompt
    if context_summary:
        full_system += f"\n\n## Topic Context\n{context_summary}"

    messages.append({"role": "system", "content": full_system})
    budget = max_tokens - count_tokens(full_system)

    # 2. Last 20 conversation turns
    recent_turns = conversation_history[-MAX_CONVERSATION_TURNS * 2 :]
    turn_tokens = sum(count_tokens(m.get("content", "")) for m in recent_turns)
    if turn_tokens > budget:
        log.warning("conversation_history_truncated", turns=len(recent_turns))
        # Keep fewer turns
        while recent_turns and turn_tokens > budget // 2:
            removed = recent_turns.pop(0)
            turn_tokens -= count_tokens(removed.get("content", ""))

    # 3. Source texts — add as assistant context if budget allows
    source_budget = budget - turn_tokens
    included_sources: list[str] = []
    for text in reversed(source_texts):
        tokens = count_tokens(text)
        if tokens <= source_budget:
            included_sources.insert(0, text)
            source_budget -= tokens
        else:
            # Truncate to fit
            if source_budget > 200:
                chars = source_budget * 4
                included_sources.insert(0, text[:chars] + "...[truncated]")
            break

    if included_sources:
        source_block = "\n\n---\n\n".join(included_sources)
        messages.append(
            {
                "role": "user",
                "content": f"## Document Sources\n\n{source_block}",
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": "I have reviewed the document sources. Ready to assist.",
            }
        )

    messages.extend(recent_turns)
    return messages
