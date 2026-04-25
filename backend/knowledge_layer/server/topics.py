from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from onyx.db.engine.sql_engine import get_session_with_current_tenant as get_session
from onyx.db.models import User
from knowledge_layer.db.models import TopicExt

router = APIRouter(tags=["knowledge-layer"])

_RAW_ROOT = Path(os.environ.get("TEAM_BRAIN_RAW_ROOT", "/raw")).resolve()


def _validate_watch_path(raw: str) -> str:
    """Resolve and validate that watch_path stays under TEAM_BRAIN_RAW_ROOT."""
    try:
        resolved = Path(raw).resolve()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid watch_path: {exc}")
    try:
        resolved.relative_to(_RAW_ROOT)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"watch_path must be inside {_RAW_ROOT}. Got: {resolved}",
        )
    return str(resolved)


async def require_user() -> User:
    """Auth gate stub for knowledge-layer endpoints.

    This function is always replaced via ``app.dependency_overrides``:
    - Production (main.py): overridden with ``onyx.auth.users.current_user``
    - Tests: overridden with a lambda returning a mock User

    Keeping auth out of this module's top-level imports avoids pulling in
    heavy transitive deps (celery, passlib, sendgrid, httpx_oauth) that are
    absent in the lean test virtualenv.
    """
    raise RuntimeError(  # pragma: no cover
        "require_user stub was invoked without an app.dependency_overrides entry. "
        "Ensure main.py calls: app.dependency_overrides[require_user] = current_user"
    )


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
def create_topic(body: TopicCreate, _: User = Depends(require_user)) -> TopicResponse:
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
            watch_path=_validate_watch_path(body.watch_path),
        )
        db.add(topic)
        db.commit()
        db.refresh(topic)
        return TopicResponse.model_validate(topic)


@router.get("/topics", response_model=list[TopicResponse])
def list_topics(_: User = Depends(require_user)) -> list[TopicResponse]:
    with get_session() as db:
        topics = db.query(TopicExt).all()
        return [TopicResponse.model_validate(t) for t in topics]


@router.get("/topics/{topic_id}", response_model=TopicResponse)
def get_topic(topic_id: int, _: User = Depends(require_user)) -> TopicResponse:
    with get_session() as db:
        topic = db.query(TopicExt).filter(TopicExt.id == topic_id).first()
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found.")
        return TopicResponse.model_validate(topic)
