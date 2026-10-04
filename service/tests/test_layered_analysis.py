"""Tests for the layered analysis: sections, sampling, the general map, and zoom."""
from __future__ import annotations

import json
import uuid

import numpy as np
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import _add_missing_columns
from app.models.graph import Edge, Node, NodeChunk
from app.models.source import Chunk, Section, Source
from app.models.topic import Topic
from app.services.analysis import AnalysisService, assign_chunks_to_nodes, uncovered_runs
from app.services.embeddings import EmbeddingService
from app.services.sampling import (
    SectionInput,
    build_section_packets,
    fingerprint_terms,
    pick_diverse,
    render_packets,
)
from app.services.sections import detect_sections, is_low_information

# ─── sections ────────────────────────────────────────────────────────────────


def test_detect_sections_from_chapter_headings():
    chunks = [
        "CHAPTER 1\nPast developments\nSome opening text about history.",
        "More text of the first chapter.",
        "CHAPTER 2\nPaths forward\nText of the second chapter.",
    ]
    spans = detect_sections(chunks)
    assert [(s.first, s.last) for s in spans] == [(0, 1), (2, 2)]
    assert spans[0].title == "CHAPTER 1 Past developments"
    assert not any(s.is_boilerplate for s in spans)


def test_detect_sections_ignores_chapter_references_in_prose():
    chunks = [
        "Chapter 1\nBeginnings\nText.",
        "Chapter 12.)\nas discussed, the argument continues here in plain prose.",
        "Chapter 7—goal system integrity, cognitive enhancement, resource acquisition, and so on at length.",
    ]
    assert len(detect_sections(chunks)) == 1


def test_detect_sections_marks_contents_and_back_matter_as_boilerplate():
    chunks = [
        "INTRODUCCIÓN\nCAPÍTULO PRIMERO\nUN TITULO\nCAPÍTULO SEGUNDO\nOTRO TITULO",  # contents
        "INTRODUCCIÓN\nEl texto empieza aquí con una idea.",
        "CAPÍTULO PRIMERO\nUN TITULO\nDesarrollo de la primera idea.",
        "Más desarrollo.",
        "Continuación del capítulo.",
        "NOTES\nCHAPTER 1: BEGINNINGS\n1. A note about something.",
        "CHAPTER 2: LATER\n1. Another note.",
    ]
    spans = detect_sections(chunks)
    by_first = {s.first: s for s in spans}
    assert by_first[0].is_boilerplate  # table of contents
    assert not by_first[1].is_boilerplate
    assert by_first[2].title.startswith("CAPÍTULO PRIMERO")
    # Chapter-titled subsections of the notes stay boilerplate
    assert by_first[5].is_boilerplate and by_first[6].is_boilerplate


def test_detect_sections_falls_back_to_windows_without_headings():
    spans = detect_sections([f"plain paragraph number {i}" for i in range(30)])
    assert len(spans) == 3
    assert spans[0].first == 0 and spans[-1].last == 29


def test_is_low_information_flags_index_and_references():
    index = "\n".join(f"term {i}  {i * 3}, {i * 7}" for i in range(20))
    references = "\n".join(
        f"Author {i}. 20{i:02d}. A study of things. Journal of Stuff {i}." for i in range(12)
    )
    prose = "The argument of this chapter is that ideas connect in more than one way.\n" * 5
    assert is_low_information(index)
    assert is_low_information(references)
    assert not is_low_information(prose)


# ─── sampling ────────────────────────────────────────────────────────────────


def test_pick_diverse_takes_one_passage_per_cluster():
    rng = np.random.default_rng(0)
    centers = np.eye(3)
    embeddings = np.vstack([c + rng.normal(0, 0.01, (5, 3)) for c in centers])
    picked = pick_diverse(embeddings, 3)
    assert sorted(i // 5 for i in picked) == [0, 1, 2]


def test_fingerprint_terms_are_distinctive_per_section():
    sections = [
        "oracle oracle oracle system system design",
        "takeoff takeoff takeoff system system speed",
        "values values values system system loading",
        "strategy strategy strategy system system policy",
    ]
    terms = fingerprint_terms(sections)
    assert terms[0][0] == "oracle" and terms[1][0] == "takeoff"
    assert all("system" not in t for t in terms)  # used everywhere: not distinctive


def test_packets_cover_every_section_within_budget():
    texts, embeddings, sections = [], [], []
    for s in range(6):
        positions = []
        for i in range(20):
            positions.append(len(texts))
            texts.append(f"section{s} passage{i} " + f"word{s} " * 150)
            vector = np.zeros(8)
            vector[s] = 1.0
            vector[6 + (i % 2)] = 0.5
            embeddings.append(vector.tolist())
        sections.append(SectionInput(title=f"Chapter {s + 1}", chunk_positions=positions))

    budget = 9_000  # the whole text is ~23k tokens
    packets = build_section_packets(sections, texts, embeddings, budget)
    rendered = render_packets(packets)

    assert len(packets) == 6
    for s in range(6):
        assert f"S{s + 1} — Chapter {s + 1}" in rendered
        assert f"section{s} passage0 " in rendered  # opening of every section
    assert all(p.passages for p in packets)
    assert len(rendered) // 4 <= budget * 1.2
    assert len(rendered) < sum(len(t) for t in texts) / 2


# ─── text assignment and coverage ────────────────────────────────────────────


def test_assign_chunks_prefers_candidates_then_similarity():
    nodes = [[1.0, 0.0], [0.0, 1.0]]
    chunks = [[1.0, 0.1], [0.1, 1.0], [0.9, 0.2]]
    assigned, similarity = assign_chunks_to_nodes(chunks, nodes, [[], [], [1]])
    assert assigned == [0, 1, 1]  # the last chunk may only go to node 1
    assert similarity[0] > 0.9


def test_assign_chunks_without_embeddings_still_assigns_everything():
    assigned, _ = assign_chunks_to_nodes([None, None, None], [None, None], [[], [], []])
    assert len(assigned) == 3 and set(assigned) <= {0, 1}


def test_uncovered_runs_finds_a_missed_region_not_scattered_outliers():
    similarity = [0.6] * 30
    for i in (10, 11, 12, 13):
        similarity[i] = 0.05
    similarity[25] = 0.05  # a single poor fit is noise
    assert uncovered_runs(similarity) == [10, 11, 12, 13]
    assert uncovered_runs([0.6] * 30) == []


# ─── service: general map and zoom ───────────────────────────────────────────

AXES = {"alpha": 0, "beta": 1, "gamma": 2}


def _vector(text_value: str) -> list[float]:
    vector = [0.01, 0.01, 0.01]
    lowered = text_value.lower()
    for word, axis in AXES.items():
        vector[axis] += lowered.count(word)
    return vector


class FakeEmbeddings(EmbeddingService):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_vector(t) for t in texts]


class ScriptedLLM:
    """Returns queued JSON responses and records the prompts it was given."""

    model_name = "scripted"

    def __init__(self, *responses: dict | str) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def complete(self, messages, stream=False, max_tokens=4096):
        self.prompts.append(messages[-1]["content"])
        response = self._responses.pop(0) if self._responses else {}
        payload = response if isinstance(response, str) else json.dumps(response)

        async def gen():
            yield payload

        return gen()


L0_RESPONSE = {
    "nodes": [
        {"label": "Alpha idea", "description": "About alpha", "sections": ["S1"]},
        {"label": "Beta idea", "description": "About beta, touching gamma", "sections": ["S2"]},
        # Section 3 (gamma) is left out on purpose: its text must still land on a node,
        # and the nearest one is "Beta idea"
    ],
    "edges": [
        {
            "from_label": "Alpha idea",
            "to_label": "Beta idea",
            "type": "causal",
            "weight": 0.7,
            "confidence": 0.9,
            "evidence": "alpha leads to beta",
        }
    ],
}


async def _source_with_chunks(db: AsyncSession, topic: Topic) -> Source:
    source = Source(
        id=str(uuid.uuid4()),
        topic_id=topic.id,
        type="text",
        name="Doc",
        extracted_text="alpha beta gamma. " * 50,
    )
    db.add(source)
    texts = []
    for chapter, word in enumerate(("alpha", "beta", "gamma"), start=1):
        texts.append(f"Chapter {chapter}\nOn {word}\n" + f"{word} opens the chapter. " * 20)
        texts.extend(f"{word} passage {i}. " + f"{word} detail. " * 20 for i in range(4))
    for order, chunk_text in enumerate(texts):
        db.add(
            Chunk(
                id=str(uuid.uuid4()),
                source_id=source.id,
                topic_id=topic.id,
                text=chunk_text,
                order=order,
                embedding_json=json.dumps(_vector(chunk_text)),
            )
        )
    await db.commit()
    return source


async def _run(generator) -> list[tuple[str, dict]]:
    return [event async for event in generator]


async def _nodes_by_label(db: AsyncSession) -> dict[str, Node]:
    result = await db.execute(select(Node))
    return {n.label: n for n in result.scalars().all()}


async def _chunk_texts_of(db: AsyncSession, node: Node) -> list[str]:
    result = await db.execute(
        select(Chunk.text)
        .join(NodeChunk, NodeChunk.chunk_id == Chunk.id)
        .where(NodeChunk.node_id == node.id)
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_general_map_samples_and_assigns_every_chunk(
    db_session: AsyncSession, sample_topic: Topic
):
    source = await _source_with_chunks(db_session, sample_topic)
    llm = ScriptedLLM(L0_RESPONSE, "## Summary\n\nText.")
    service = AnalysisService(db_session, llm, FakeEmbeddings(), l0_full_read_tokens=200)

    events = await _run(service.analyze_l0(sample_topic.id, source))
    await db_session.commit()

    done = dict(events)["done"]
    assert done["sampled"] is True
    assert done["read_tokens"] < done["content_tokens"]  # the model did not read it all
    assert len(llm.prompts) == 2  # one call for the map, one for the document

    sections = (await db_session.execute(select(Section))).scalars().all()
    assert len(sections) == 3

    nodes = await _nodes_by_label(db_session)
    assert set(nodes) == {"Alpha idea", "Beta idea"}
    assert all(n.level == 0 and n.parent_id is None for n in nodes.values())

    # No section left out: all 15 chunks belong to exactly one node
    links = (await db_session.execute(select(NodeChunk))).scalars().all()
    assert len(links) == 15 and len({link.chunk_id for link in links}) == 15
    alpha_texts = await _chunk_texts_of(db_session, nodes["Alpha idea"])
    beta_texts = await _chunk_texts_of(db_session, nodes["Beta idea"])
    assert sum("alpha passage" in t for t in alpha_texts) == 4
    assert sum("beta passage" in t for t in beta_texts) == 4
    assert sum("gamma passage" in t for t in beta_texts) == 4  # the left-out section
    assert round(sum(n.coverage for n in nodes.values()), 2) == 1.0

    edge = (await db_session.execute(select(Edge))).scalar_one()
    assert edge.basis == "sampled"
    assert edge.confidence <= 0.6  # provisional until the text is read
    assert edge.evidence == "alpha leads to beta"


@pytest.mark.asyncio
async def test_short_source_is_read_whole_and_reanalysis_replaces_the_map(
    db_session: AsyncSession, sample_topic: Topic
):
    source = await _source_with_chunks(db_session, sample_topic)
    llm = ScriptedLLM(L0_RESPONSE, "Summary.", L0_RESPONSE, "Summary.")
    service = AnalysisService(db_session, llm, FakeEmbeddings(), l0_full_read_tokens=100_000)

    events = await _run(service.analyze_l0(sample_topic.id, source))
    assert dict(events)["done"]["sampled"] is False
    edge = (await db_session.execute(select(Edge))).scalar_one()
    assert edge.basis == "read" and edge.confidence == 0.9

    await _run(service.analyze_l0(sample_topic.id, source))
    await db_session.commit()
    assert len((await db_session.execute(select(Node))).scalars().all()) == 2
    assert len((await db_session.execute(select(NodeChunk))).scalars().all()) == 15


ZOOM_RESPONSE = {
    "nodes": [
        {"label": "Alpha opening", "description": "How alpha opens"},
        {"label": "Alpha detail", "description": "The alpha detail"},
        {"label": "Beta idea", "description": "Already on the map"},
    ],
    "edges": [
        {
            "from_label": "Alpha detail",
            "to_label": "Beta idea",
            "type": "causal",
            "weight": 0.8,
            "confidence": 0.9,
            "evidence": "the detail drives beta",
        },
        {"from_label": "Alpha opening", "to_label": "Alpha detail", "type": "relational"},
    ],
    "link_reviews": [
        {"other_label": "Beta idea", "verdict": "confirmed", "evidence": "stated in the text"}
    ],
}


@pytest.mark.asyncio
async def test_zoom_reads_only_the_nodes_text_and_revises_links(
    db_session: AsyncSession, sample_topic: Topic
):
    source = await _source_with_chunks(db_session, sample_topic)
    llm = ScriptedLLM(L0_RESPONSE, "Summary.", ZOOM_RESPONSE)
    service = AnalysisService(db_session, llm, FakeEmbeddings(), l0_full_read_tokens=200)
    await _run(service.analyze_l0(sample_topic.id, source))
    await db_session.commit()

    alpha = (await _nodes_by_label(db_session))["Alpha idea"]
    events = await _run(service.zoom(sample_topic.id, alpha))
    await db_session.commit()

    zoom_prompt = llm.prompts[-1]
    text_part = zoom_prompt.split("---")[1]
    assert "alpha passage 0" in text_part
    assert "beta passage" not in text_part and "gamma passage" not in text_part
    assert "Beta idea" in zoom_prompt  # the rest of the map is listed for linking

    done = dict(events)["done"]
    assert done["sub_nodes"] == 2 and done["fully_read"] is True

    nodes = await _nodes_by_label(db_session)
    assert len(nodes) == 4  # "Beta idea" was not duplicated
    assert nodes["Alpha idea"].status == "zoomed"
    for label in ("Alpha opening", "Alpha detail"):
        assert nodes[label].level == 1 and nodes[label].parent_id == alpha.id

    # Every chunk of the parent is reachable through a sub-node
    parent_chunks = set(await _chunk_texts_of(db_session, nodes["Alpha idea"]))
    sub_chunks = set(await _chunk_texts_of(db_session, nodes["Alpha opening"])) | set(
        await _chunk_texts_of(db_session, nodes["Alpha detail"])
    )
    assert parent_chunks == sub_chunks

    edges = (await db_session.execute(select(Edge))).scalars().all()
    by_pair = {frozenset((e.from_node_id, e.to_node_id)): e for e in edges}

    def edge_between(a: str, b: str) -> Edge:
        return by_pair[frozenset((nodes[a].id, nodes[b].id))]

    # The sampled top-level link is now confirmed by the text that was read
    top = edge_between("Alpha idea", "Beta idea")
    assert top.basis == "read" and top.confidence >= 0.8 and top.status == "active"
    # New cross-link from a sub-concept to another part of the map
    cross = edge_between("Alpha detail", "Beta idea")
    assert cross.basis == "read" and cross.type == "causal"
    assert edge_between("Alpha idea", "Alpha detail").type == "hierarchical"
    assert edge_between("Alpha opening", "Alpha detail").basis == "read"


@pytest.mark.asyncio
async def test_zoom_marks_link_unsupported_only_when_both_ends_were_read(
    db_session: AsyncSession, sample_topic: Topic
):
    source = await _source_with_chunks(db_session, sample_topic)
    review = {
        "nodes": [{"label": "Sub", "description": "alpha sub"}],
        "edges": [],
        "link_reviews": [{"other_label": "Beta idea", "verdict": "unsupported"}],
    }
    review_beta = {
        "nodes": [{"label": "Sub beta", "description": "beta sub"}],
        "edges": [],
        "link_reviews": [{"other_label": "Alpha idea", "verdict": "unsupported"}],
    }
    llm = ScriptedLLM(L0_RESPONSE, "Summary.", review, review_beta)
    service = AnalysisService(db_session, llm, FakeEmbeddings(), l0_full_read_tokens=200)
    await _run(service.analyze_l0(sample_topic.id, source))
    nodes = await _nodes_by_label(db_session)

    await _run(service.zoom(sample_topic.id, nodes["Alpha idea"]))
    edge = (
        await db_session.execute(select(Edge).where(Edge.type == "causal"))
    ).scalar_one()
    assert edge.status == "active" and edge.confidence < 0.6  # faded, not removed

    await _run(service.zoom(sample_topic.id, nodes["Beta idea"]))
    assert edge.status == "unsupported"


@pytest.mark.asyncio
async def test_zoom_on_a_node_without_assigned_text_uses_the_most_similar_passages(
    db_session: AsyncSession, sample_topic: Topic
):
    source = await _source_with_chunks(db_session, sample_topic)
    legacy = Node(
        id=str(uuid.uuid4()),
        topic_id=sample_topic.id,
        source_id=source.id,
        label="Gamma idea",
        description="About gamma",
    )
    db_session.add(legacy)
    await db_session.commit()

    llm = ScriptedLLM({"nodes": [{"label": "Gamma sub", "description": "gamma"}], "edges": []})
    service = AnalysisService(db_session, llm, FakeEmbeddings(), zoom_read_tokens=600)
    events = await _run(service.zoom(sample_topic.id, legacy))

    text_part = llm.prompts[-1].split("---")[1]
    assert "gamma" in text_part and "alpha passage" not in text_part
    assert dict(events)["done"]["fully_read"] is False


# ─── schema upgrade of an existing database ──────────────────────────────────


@pytest.mark.asyncio
async def test_missing_columns_are_added_to_an_existing_database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE chunks (id VARCHAR(36) PRIMARY KEY)"))
        await conn.execute(text("CREATE TABLE nodes (id VARCHAR(36) PRIMARY KEY)"))
        await conn.execute(
            text("CREATE TABLE edges (id VARCHAR(36) PRIMARY KEY, confidence FLOAT)")
        )
        await conn.execute(text("INSERT INTO edges (id, confidence) VALUES ('e1', 0.5)"))
        await conn.run_sync(_add_missing_columns)
        await conn.run_sync(_add_missing_columns)  # idempotent
        row = (await conn.execute(text("SELECT basis, status FROM edges"))).one()
        level = (await conn.execute(text("SELECT count(level) FROM nodes"))).scalar()
    await engine.dispose()
    assert row == ("read", "active")
    assert level == 0
