"""Fact-check router — on-demand web verification of source claims."""
from __future__ import annotations

import json
import re
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.source import Source
from app.models.topic import Topic
from app.routers.deps import get_current_user, get_llm_adapter
from app.services.llm.base import LLMAdapter

log = structlog.get_logger()

router = APIRouter(prefix="/topics/{topic_id}/sources/{source_id}", tags=["fact-check"])

# ─── Prompts ─────────────────────────────────────────────────────────────────

_CLAIMS_PROMPT = """Extract 5-8 specific, verifiable claims from the following text.
A verifiable claim must be: a concrete fact, statistic, attribution to a named person/study/institution,
or a specific event. Do NOT include vague generalizations or opinions.

Return ONLY a JSON array of strings, e.g.:
["The study involved 1,200 participants", "WHO reported X% increase in 2022", ...]

Text:
"""

_VERDICT_PROMPT = """You are a fact-checker. Given a claim and web search results, determine whether the claim is:
- "verified": evidence clearly supports the claim
- "contradicted": evidence clearly contradicts the claim
- "unverified": evidence is ambiguous, absent, or irrelevant

Return a JSON object:
{{
  "verdict": "verified" | "contradicted" | "unverified",
  "evidence": "<1-2 sentence summary of what the evidence shows>"
}}

Claim: {claim}

Search results:
{results}
"""

# DuckDuckGo lite search (no API key needed)
_DDG_URL = "https://html.duckduckgo.com/html/"
_SEARCH_TIMEOUT = 10.0
_MAX_RESULT_CHARS = 1200
_TOP_RESULTS = 3


# ─── Response schemas ────────────────────────────────────────────────────────

class ClaimResult(BaseModel):
    claim: str
    verdict: str          # "verified" | "contradicted" | "unverified"
    evidence: str
    source_url: str


class FactCheckResponse(BaseModel):
    claims: list[ClaimResult]
    fact_check_score: int
    quality_score_updated: int | None


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> Any:
    """Extract JSON from LLM response."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    patterns = [
        r"```json\s*([\s\S]*?)\s*```",
        r"```\s*([\s\S]*?)\s*```",
        r"\{[\s\S]*\}",
        r"\[[\s\S]*\]",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            candidate = match.group(1) if "```" in pattern else match.group(0)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    return None


async def _web_search(query: str) -> list[dict]:
    """
    Search DuckDuckGo HTML endpoint. Returns list of {title, url, snippet}.
    Falls back to empty list on any error (degraded mode, not fatal).
    """
    try:
        async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT, follow_redirects=True) as client:
            resp = await client.post(
                _DDG_URL,
                data={"q": query, "b": "", "kl": ""},
                headers={"User-Agent": "Mozilla/5.0 (llull fact-checker)"},
            )
            resp.raise_for_status()
            html = resp.text

        # Extract result snippets with simple regex (DDG HTML is stable enough)
        results = []
        # Match result links
        link_pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            re.DOTALL,
        )
        snippet_pattern = re.compile(
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
            re.DOTALL,
        )
        links = link_pattern.findall(html)
        snippets = snippet_pattern.findall(html)

        for i, (url, title) in enumerate(links[:_TOP_RESULTS]):
            snippet = snippets[i] if i < len(snippets) else ""
            # Strip HTML tags
            clean_title = re.sub(r"<[^>]+>", "", title).strip()
            clean_snippet = re.sub(r"<[^>]+>", "", snippet).strip()
            results.append({
                "url": url,
                "title": clean_title,
                "snippet": clean_snippet[:_MAX_RESULT_CHARS],
            })
        return results

    except Exception as e:
        log.warning("web_search_failed", query=query[:80], error=str(e))
        return []


async def _extract_claims(text: str, llm: LLMAdapter) -> list[str]:
    """Ask the LLM to extract verifiable claims from the source text."""
    sample = text[:6000]
    messages = [{"role": "user", "content": _CLAIMS_PROMPT + sample}]
    response = ""
    async for token in await llm.complete(messages, stream=False):
        response += token

    parsed = _extract_json(response)
    if isinstance(parsed, list):
        return [str(c) for c in parsed[:8]]
    return []


async def _evaluate_claim(
    claim: str,
    search_results: list[dict],
    llm: LLMAdapter,
) -> tuple[str, str]:
    """
    Ask the LLM to evaluate a claim against search results.
    Returns (verdict, evidence_summary).
    """
    if not search_results:
        return "unverified", "No web search results available."

    results_text = "\n\n".join(
        f"[{i+1}] {r['title']}\nURL: {r['url']}\n{r['snippet']}"
        for i, r in enumerate(search_results)
    )
    prompt = _VERDICT_PROMPT.format(claim=claim, results=results_text)
    messages = [{"role": "user", "content": prompt}]

    response = ""
    async for token in await llm.complete(messages, stream=False):
        response += token

    parsed = _extract_json(response)
    if isinstance(parsed, dict):
        verdict = parsed.get("verdict", "unverified")
        if verdict not in ("verified", "contradicted", "unverified"):
            verdict = "unverified"
        return verdict, parsed.get("evidence", "")

    return "unverified", "Could not parse LLM evaluation."


# ─── Endpoint ────────────────────────────────────────────────────────────────

@router.post("/fact-check", response_model=FactCheckResponse)
async def fact_check_source(
    topic_id: str,
    source_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    llm: LLMAdapter = Depends(get_llm_adapter),
) -> FactCheckResponse:
    """
    Run on-demand web fact-check on a source.

    1. Extracts 5-8 verifiable claims via LLM
    2. Web-searches each claim (DuckDuckGo)
    3. LLM evaluates search results → verdict per claim
    4. Computes fact_check_score and adjusts quality_score
    5. Persists results to the source record
    """
    # Verify topic ownership
    topic_result = await db.execute(
        select(Topic).where(Topic.id == topic_id, Topic.user_id == user_id)
    )
    if topic_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    # Fetch source
    source_result = await db.execute(
        select(Source).where(Source.id == source_id, Source.topic_id == topic_id)
    )
    source = source_result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    if not source.extracted_text:
        raise HTTPException(status_code=422, detail="Source has no extracted text to fact-check")

    log.info("fact_check_start", source_id=source_id)

    # Step 1: Extract claims
    claims = await _extract_claims(source.extracted_text, llm)
    if not claims:
        raise HTTPException(status_code=422, detail="Could not extract verifiable claims from this source")

    # Step 2 + 3: Search & evaluate each claim
    claim_results: list[ClaimResult] = []
    for claim in claims:
        search_results = await _web_search(claim)
        top_url = search_results[0]["url"] if search_results else ""
        verdict, evidence = await _evaluate_claim(claim, search_results, llm)
        claim_results.append(ClaimResult(
            claim=claim,
            verdict=verdict,
            evidence=evidence,
            source_url=top_url,
        ))

    # Step 4: Compute fact_check_score
    verified_count = sum(1 for r in claim_results if r.verdict == "verified")
    total = len(claim_results)
    fact_check_score = int((verified_count / total) * 100) if total else 0

    # Adjust quality score: 60% original + 40% fact_check
    quality_updated: int | None = None
    if source.quality_score is not None:
        quality_updated = int(source.quality_score * 0.6 + fact_check_score * 0.4)
    elif fact_check_score > 0:
        # No prior quality score — use fact_check alone as proxy
        quality_updated = fact_check_score

    # Step 5: Persist
    source.fact_check_result = json.dumps([r.model_dump() for r in claim_results])
    source.fact_check_score = fact_check_score
    if quality_updated is not None:
        source.quality_score = quality_updated

    await db.flush()
    log.info(
        "fact_check_complete",
        source_id=source_id,
        total_claims=total,
        verified=verified_count,
        fact_check_score=fact_check_score,
    )

    return FactCheckResponse(
        claims=claim_results,
        fact_check_score=fact_check_score,
        quality_score_updated=quality_updated,
    )
