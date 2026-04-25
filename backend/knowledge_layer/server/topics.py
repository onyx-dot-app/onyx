from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from onyx.db.engine.sql_engine import get_session_with_current_tenant as get_session
from knowledge_layer.db.models import TopicExt

router = APIRouter(tags=["knowledge-layer"])


class TopicCreate(BaseModel):
    name: str
    description: str = ""
    watch_path: str


class TopicResponse(BaseModel):
    id: int | None = None
    name: str
    description: str
    watch_path: str

    model_config = {"from_attributes": True}


@router.post("/topics", response_model=TopicResponse, status_code=status.HTTP_201_CREATED)
def create_topic(body: TopicCreate) -> TopicResponse:
    with get_session() as db:
        existing = db.query(TopicExt).filter(TopicExt.name == body.name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Topic '{body.name}' already exists.",
            )
        topic = TopicExt(
            name=body.name,
            description=body.description,
            watch_path=body.watch_path,
        )
        db.add(topic)
        db.commit()
        db.refresh(topic)
        return TopicResponse.model_validate(topic)


@router.get("/topics", response_model=list[TopicResponse])
def list_topics() -> list[TopicResponse]:
    with get_session() as db:
        topics = db.query(TopicExt).all()
        return [TopicResponse.model_validate(t) for t in topics]


@router.get("/topics/{topic_id}", response_model=TopicResponse)
def get_topic(topic_id: int) -> TopicResponse:
    with get_session() as db:
        topic = db.query(TopicExt).filter(TopicExt.id == topic_id).first()
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found.")
        return TopicResponse.model_validate(topic)
