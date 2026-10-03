"""Source quality rating service."""
from __future__ import annotations

import json
import re

import structlog

from app.services.analysis import detect_language, language_name_for
from app.services.llm.base import LLMAdapter

log = structlog.get_logger()

RATING_PROMPT = """You are a document quality analyst. Analyze the following text and return a JSON object with exactly this structure:

{
  "ai_suspicion": <int 0-100 or null>,
  "ai_suspicion_reason": "<1-2 sentences in __LANGUAGE__>",
  "quality_score": <int 0-100 or null>,
  "quality_reason": "<1-2 sentences in __LANGUAGE__>"
}

IMPORTANT: Write both reasons in __LANGUAGE__, regardless of any other language that appears in the text.

AI SUSPICION criteria (do NOT consider grammar errors or lack thereof):
- Excessive repetitive use of superlative adjectives ("comprehensive", "robust", "innovative", "seamless", "cutting-edge")
- Overly uniform, predictable structure (intro → bullet points → conclusion with no variation)
- Formulaic transitions ("Furthermore", "Moreover", "It is worth noting that", "It is important to highlight")
- Absence of personal voice, opinion, anecdote, or idiomatic expressions
- Excessive hedging ("one might argue", "it could be suggested")
- Unusual uniformity in paragraph and sentence length
- Generic examples that lack specificity

QUALITY criteria:
- Concreteness: specific facts, data, examples vs. vague generalizations
- Articulation: clear logical flow, well-developed arguments
- Citation of credible sources: named authors, studies, papers, institutions, statistics with attribution
- Low fluff: penalize filler phrases, repetition, padding
- Originality: novel insights vs. recycled common knowledge

Score 0 = very poor, 100 = excellent.

If the text is too short (<300 words), return ai_suspicion=null and quality_score=null with reasons explaining why.

Document text:
"""

# Minimum word count to attempt rating
MIN_WORDS = 300
# Total characters sent to LLM across all samples
MAX_SAMPLE_CHARS = 8000
# Number of evenly-distributed samples
N_SAMPLES = 5


def _distributed_sample(text: str, total_chars: int = MAX_SAMPLE_CHARS, n_samples: int = N_SAMPLES) -> str:
    """
    Take N evenly-distributed samples across the full text.
    Ensures the rating covers beginning, middle, and end of document.
    """
    if len(text) <= total_chars:
        return text

    sample_size = total_chars // n_samples
    step = len(text) // n_samples
    samples = []
    for i in range(n_samples):
        start = i * step
        samples.append(text[start: start + sample_size])

    return "\n\n---\n\n".join(samples)


def _extract_json(text: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    patterns = [
        r"```json\s*([\s\S]*?)\s*```",
        r"```\s*([\s\S]*?)\s*```",
        r"\{[\s\S]*\}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            candidate = match.group(1) if "```" in pattern else match.group(0)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    log.warning("rating_json_extract_failed", preview=text[:200])
    return None


class RatingService:
    """Rates sources for AI suspicion and content quality."""

    def __init__(self, llm: LLMAdapter) -> None:
        self._llm = llm

    async def rate_source(self, text: str) -> dict:
        """
        Rate a source for AI suspicion and quality.

        Returns dict with ai_suspicion, ai_suspicion_reason, quality_score, quality_reason.
        Returns null scores if text is too short or LLM fails.
        """
        word_count = len(text.split())
        if word_count < MIN_WORDS:
            reason = f"Text too short ({word_count} words) to evaluate reliably."
            return {
                "ai_suspicion": None,
                "ai_suspicion_reason": reason,
                "quality_score": None,
                "quality_reason": reason,
            }

        # Sample evenly from across the full document so beginning, middle,
        # and end are all represented in the rating
        sample = _distributed_sample(text)
        # Name the language explicitly: left to infer "the document's language",
        # the model has answered in a different one.
        language_name = language_name_for(detect_language(text))
        prompt = RATING_PROMPT.replace("__LANGUAGE__", language_name)
        messages = [{"role": "user", "content": prompt + sample}]

        try:
            response = ""
            async for token in await self._llm.complete(messages, stream=False):
                response += token

            parsed = _extract_json(response)
            if not parsed:
                log.warning("rating_parse_failed", word_count=word_count)
                return _fallback_null_result("LLM returned unparseable response.")

            # Clamp scores to 0-100 range if present
            for key in ("ai_suspicion", "quality_score", "fact_check_score"):
                val = parsed.get(key)
                if isinstance(val, (int, float)):
                    parsed[key] = max(0, min(100, int(val)))

            return {
                "ai_suspicion": parsed.get("ai_suspicion"),
                "ai_suspicion_reason": parsed.get("ai_suspicion_reason", ""),
                "quality_score": parsed.get("quality_score"),
                "quality_reason": parsed.get("quality_reason", ""),
            }

        except Exception as e:
            log.error("rating_failed", error=str(e))
            return _fallback_null_result(f"Rating failed: {e}")


def _fallback_null_result(reason: str) -> dict:
    return {
        "ai_suspicion": None,
        "ai_suspicion_reason": reason,
        "quality_score": None,
        "quality_reason": reason,
    }
