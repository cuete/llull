"""Choose which passages of a source the model reads to build the general map.

Selection uses only the text's structure and the chunk embeddings computed at ingest,
so deciding what to read costs no LLM tokens.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from app.services.sections import is_low_information

CHARS_PER_TOKEN = 4
OPENING_CHARS = 1200
CLOSING_CHARS = 800
FINGERPRINT_TERMS = 12
MAX_KEY_STATEMENTS = 2
KEY_STATEMENT_CHARS = 240

_WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# Phrases authors use when stating a thesis, a definition or a conclusion (EN/ES)
_SIGNAL = re.compile(
    r"\b(?:in summary|in conclusion|to summarize|we argue|i argue|the key|the central|"
    r"the main|this chapter|is defined as|we can define|it follows that|therefore|"
    r"en resumen|en conclusi[oó]n|en s[ií]ntesis|sostenemos|la clave|lo esencial|"
    r"el principal|este cap[ií]tulo|se define como|por tanto|por lo tanto|por eso)\b",
    re.IGNORECASE,
)


_STOPWORDS = frozenset(
    "that this with from have they their there which would could should about these those "
    "what when where while been being were will into than then them also such some more most "
    "other only over very much many because between through after before each both does "
    "para como pero este esta estos estas esto sino cuando donde desde hasta entre sobre "
    "también porque puede pueden todo toda todos todas cada otro otra otros otras "
    "nuestro nuestra nuestros nuestras tiene tienen hace hacer solo sólo más muy "
    "según ante bajo contra durante mediante aquí así".split()
)


@dataclass
class SectionInput:
    """A content section: its title and the positions of its chunks in the source."""

    title: str
    chunk_positions: list[int]


@dataclass
class SectionPacket:
    """What the model is shown for one section."""

    title: str
    total_chunks: int
    terms: list[str] = field(default_factory=list)
    key_statements: list[str] = field(default_factory=list)
    opening: str = ""
    closing: str = ""
    # (chunk position, text) of the representative and bridge passages, in source order
    passages: list[tuple[int, str]] = field(default_factory=list)


def _tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN + 1


def _unit(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1.0, norms)


def fingerprint_terms(section_texts: list[str], top: int = FINGERPRINT_TERMS) -> list[list[str]]:
    """Terms distinctive to each section compared with the others (tf-idf on words)."""
    counts = [Counter(w.lower() for w in _WORD.findall(text)) for text in section_texts]
    document_frequency: Counter[str] = Counter()
    for c in counts:
        document_frequency.update(c.keys())
    n = len(section_texts)
    # With enough sections, words used almost everywhere are function words or the
    # document's general subject; with few, fall back to a stopword list.
    by_frequency = n >= 4
    result: list[list[str]] = []
    for c in counts:
        total = sum(c.values()) or 1
        scored: dict[str, float] = {}
        for term, freq in c.items():
            if freq < 2:
                continue
            if by_frequency:
                df = document_frequency[term]
                if df / n > 0.8:
                    continue
                scored[term] = (freq / total) * math.log(n / df + 1)
            elif term not in _STOPWORDS:
                scored[term] = freq / total
        result.append(sorted(scored, key=scored.get, reverse=True)[:top])
    return result


def spread(embeddings: np.ndarray) -> float:
    """How varied a set of passages is: mean distance to their centroid (0 = identical)."""
    if len(embeddings) < 2:
        return 0.0
    unit = _unit(embeddings)
    centroid = unit.mean(axis=0)
    centroid /= np.linalg.norm(centroid) or 1.0
    return float(np.mean(1.0 - unit @ centroid))


def pick_diverse(embeddings: np.ndarray, k: int) -> list[int]:
    """Indexes of k passages covering distinct subtopics: one medoid per cluster."""
    n = len(embeddings)
    if k >= n:
        return list(range(n))
    if k <= 0:
        return []
    unit = _unit(embeddings)

    # Farthest-point seeding, starting from the passage closest to the overall centroid
    centroid = unit.mean(axis=0)
    seeds = [int(np.argmax(unit @ centroid))]
    nearest = unit @ unit[seeds[0]]
    while len(seeds) < k:
        candidate = int(np.argmin(nearest))
        seeds.append(candidate)
        nearest = np.maximum(nearest, unit @ unit[candidate])

    centers = unit[seeds]
    for _ in range(5):
        assignment = np.argmax(unit @ centers.T, axis=1)
        new_centers = np.array([
            unit[assignment == c].mean(axis=0) if np.any(assignment == c) else centers[c]
            for c in range(k)
        ])
        new_centers = _unit(new_centers)
        if np.allclose(new_centers, centers):
            break
        centers = new_centers

    assignment = np.argmax(unit @ centers.T, axis=1)
    picked: list[int] = []
    for c in range(k):
        members = np.where(assignment == c)[0]
        if len(members):
            picked.append(int(members[np.argmax(unit[members] @ centers[c])]))
    return sorted(set(picked))


def _key_statements(texts: list[str]) -> list[str]:
    found: list[str] = []
    for text in texts:
        for sentence in _SENTENCE_END.split(text.replace("\n", " ")):
            sentence = sentence.strip()
            if 60 <= len(sentence) <= KEY_STATEMENT_CHARS and _SIGNAL.search(sentence):
                found.append(sentence)
                if len(found) >= MAX_KEY_STATEMENTS:
                    return found
    return found


def _bridge_position(
    section_index: int,
    usable: list[list[int]],
    unit: np.ndarray,
) -> int | None:
    """The passage of a section most similar to passages of non-adjacent sections."""
    own = usable[section_index]
    others = [
        p
        for j, positions in enumerate(usable)
        if abs(j - section_index) > 1  # neighbours share overlapping text
        for p in positions
    ]
    if not own or not others:
        return None
    similarity = unit[own] @ unit[others].T
    return own[int(np.argmax(similarity.max(axis=1)))]


def build_section_packets(
    sections: list[SectionInput],
    chunk_texts: list[str],
    chunk_embeddings: list[list[float] | None],
    token_budget: int,
) -> list[SectionPacket]:
    """
    Build one packet per section within token_budget.

    Every section gets a floor (title, distinctive terms, opening and closing text), so
    none is left out. The remaining budget buys representative passages, shared out by
    how varied each section is rather than by its length.
    """
    usable = [
        [p for p in s.chunk_positions if not is_low_information(chunk_texts[p])] or s.chunk_positions
        for s in sections
    ]
    terms = fingerprint_terms(
        ["\n".join(chunk_texts[p] for p in positions) for positions in usable]
    )

    packets: list[SectionPacket] = []
    for section, positions, section_terms in zip(sections, usable, terms):
        packets.append(
            SectionPacket(
                title=section.title,
                total_chunks=len(section.chunk_positions),
                terms=section_terms,
                key_statements=_key_statements([chunk_texts[p] for p in positions]),
                opening=chunk_texts[positions[0]][:OPENING_CHARS],
                closing=chunk_texts[positions[-1]][-CLOSING_CHARS:] if len(positions) > 1 else "",
            )
        )

    floor = sum(_tokens(render_packet(i, p)) for i, p in enumerate(packets))
    average_chunk = max(1, sum(_tokens(chunk_texts[p]) for ps in usable for p in ps) // max(
        1, sum(len(ps) for ps in usable)
    ))
    extra_passages = max(0, (token_budget - floor) // average_chunk)

    has_embeddings = all(chunk_embeddings[p] is not None for ps in usable for p in ps)
    if has_embeddings and extra_passages:
        dimension = len(next(e for e in chunk_embeddings if e is not None))
        matrix = np.zeros((len(chunk_texts), dimension), dtype=np.float32)
        for position, embedding in enumerate(chunk_embeddings):
            if embedding is not None:
                matrix[position] = embedding
        unit = _unit(matrix)
        # Opening and closing are already shown; pick from the passages in between
        inner = [ps[1:-1] if len(ps) > 2 else [] for ps in usable]
        weights = [
            spread(matrix[ps]) * math.log1p(len(ps)) if ps else 0.0 for ps in inner
        ]
        total_weight = sum(weights) or 1.0
        for index, (packet, positions) in enumerate(zip(packets, inner)):
            if not positions:
                continue
            share = round(extra_passages * weights[index] / total_weight)
            chosen = {positions[i] for i in pick_diverse(matrix[positions], max(1, share))}
            bridge = _bridge_position(index, inner, unit)
            if bridge is not None and len(chosen) < len(positions):
                chosen.add(bridge)
            packet.passages = [(p, chunk_texts[p]) for p in sorted(chosen)]
    elif extra_passages:
        # No embeddings: evenly spaced passages
        total_inner = sum(max(0, len(ps) - 2) for ps in usable) or 1
        for packet, positions in zip(packets, usable):
            inner_positions = positions[1:-1]
            if not inner_positions:
                continue
            count = max(1, round(extra_passages * len(inner_positions) / total_inner))
            step = max(1, len(inner_positions) // count)
            packet.passages = [(p, chunk_texts[p]) for p in inner_positions[step // 2 :: step]]

    return packets


def render_packet(index: int, packet: SectionPacket) -> str:
    shown = len(packet.passages) + (1 if packet.opening else 0) + (1 if packet.closing else 0)
    lines = [
        f"## S{index + 1} — {packet.title or 'Untitled section'} "
        f"({shown} of {packet.total_chunks} passages shown)"
    ]
    if packet.terms:
        lines.append("Distinctive terms (from the whole section): " + ", ".join(packet.terms))
    if packet.key_statements:
        lines.append("Key statements:")
        lines.extend(f"- {s}" for s in packet.key_statements)
    if packet.opening:
        lines.append(f"[opening]\n{packet.opening}")
    for _, text in packet.passages:
        lines.append(f"[passage]\n{text}")
    if packet.closing:
        lines.append(f"[closing]\n{packet.closing}")
    return "\n".join(lines)


def render_packets(packets: list[SectionPacket]) -> str:
    return "\n\n".join(render_packet(i, p) for i, p in enumerate(packets))
