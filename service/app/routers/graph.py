"""Graph router — nodes and edges."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.graph import Edge, Node
from app.models.topic import Topic
from app.routers.deps import get_current_user
from app.schemas.graph import EdgeResponse, EdgeUpdate, GraphResponse, NodeResponse

router = APIRouter(prefix="/topics/{topic_id}", tags=["graph"])


@router.get("/graph", response_model=GraphResponse)
async def get_graph(
    topic_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GraphResponse:
    await _get_topic_or_404(db, topic_id, user_id)

    nodes_result = await db.execute(
        select(Node).where(Node.topic_id == topic_id).order_by(Node.created_at)
    )
    nodes = list(nodes_result.scalars().all())
    node_ids = {n.id for n in nodes}

    edges_result = await db.execute(
        select(Edge).where(
            Edge.from_node_id.in_(node_ids),
            Edge.to_node_id.in_(node_ids),
        )
    )
    edges = list(edges_result.scalars().all())

    return GraphResponse(
        nodes=[NodeResponse.model_validate(n) for n in nodes],
        edges=[EdgeResponse.model_validate(e) for e in edges],
    )


@router.patch("/edges/{edge_id}", response_model=EdgeResponse)
async def update_edge_weight(
    topic_id: str,
    edge_id: str,
    body: EdgeUpdate,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Edge:
    await _get_topic_or_404(db, topic_id, user_id)

    result = await db.execute(select(Edge).where(Edge.id == edge_id))
    edge = result.scalar_one_or_none()
    if edge is None:
        raise HTTPException(status_code=404, detail="Edge not found")

    # Verify edge belongs to this topic
    from_node_result = await db.execute(
        select(Node).where(Node.id == edge.from_node_id, Node.topic_id == topic_id)
    )
    if from_node_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Edge not found")

    edge.weight = body.weight
    await db.flush()
    await db.refresh(edge)
    return edge


async def _get_topic_or_404(db: AsyncSession, topic_id: str, user_id: str) -> Topic:
    result = await db.execute(
        select(Topic).where(Topic.id == topic_id, Topic.user_id == user_id)
    )
    topic = result.scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic
