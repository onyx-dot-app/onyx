from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from onyx.db.engine.sql_engine import get_session
from knowledge_layer.db.models import TopicExt, WikiPage
from knowledge_layer.providers.base import WikiPageDraft
from knowledge_layer.providers.claude import ClaudeProvider

router = APIRouter(tags=["knowledge-layer"])


async def require_user() -> None:  # type: ignore[return]
    """Auth stub — overridden by main.py dependency_overrides with real current_user."""
    raise RuntimeError(
        "require_user stub was invoked without an app.dependency_overrides entry. "
        "Ensure main.py calls: app.dependency_overrides[require_user] = current_user"
    )


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[str]


@router.post("/topics/{topic_id}/query", response_model=QueryResponse)
def query_topic(
    topic_id: int,
    body: QueryRequest,
    _: None = Depends(require_user),
) -> QueryResponse:
    with get_session() as db:
        topic = db.query(TopicExt).filter(TopicExt.id == topic_id).first()
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found.")

        pages = db.query(WikiPage).filter(WikiPage.topic_id == topic_id).all()
        wiki_page_drafts = [
            WikiPageDraft(slug=p.slug, title=p.title, content=p.content)
            for p in pages
        ]

    provider = ClaudeProvider()
    result = provider.query_call(question=body.question, wiki_pages=wiki_page_drafts)

    return QueryResponse(answer=result.answer, citations=result.citations)
