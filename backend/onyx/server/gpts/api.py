import math
from datetime import datetime
from datetime import timezone

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.context.search.models import SearchRequest
from onyx.context.search.pipeline import SearchPipeline
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.llm.factory import get_default_llms
from onyx.server.onyx_api.ingestion import api_key_dep
from onyx.utils.logger import setup_logger


logger = setup_logger()


router = APIRouter(prefix="/gpts")


def time_ago(dt: datetime) -> str:
    # Calculate time difference
    now = datetime.now(timezone.utc)
    diff = now - dt.astimezone(timezone.utc)

    # Convert difference to minutes
    minutes = diff.total_seconds() / 60

    # Determine the appropriate unit and calculate the age
    if minutes < 60:
        return f"~{math.floor(minutes)} minutes"
    hours = minutes / 60
    if hours < 24:
        return f"~{math.floor(hours)} hours"
    days = hours / 24
    if days < 7:
        return f"~{math.floor(days)} days"
    weeks = days / 7
    if weeks < 4:
        return f"~{math.floor(weeks)} weeks"
    months = days / 30
    return f"~{math.floor(months)} months"


class GptSearchRequest(BaseModel):
    query: str


class GptDocChunk(BaseModel):
    title: str
    content: str
    source_type: str
    link: str
    metadata: dict[str, str | list[str]]
    document_age: str


class GptSearchResponse(BaseModel):
    matching_document_chunks: list[GptDocChunk]


@router.post("/gpt-document-search")
def gpt_search(
    search_request: GptSearchRequest,
    _: User | None = Depends(api_key_dep),
    db_session: Session = Depends(get_session),
) -> GptSearchResponse:
    llm, fast_llm = get_default_llms()
    top_sections = SearchPipeline(
        search_request=SearchRequest(
            query=search_request.query,
        ),
        user=None,
        llm=llm,
        fast_llm=fast_llm,
        skip_query_analysis=True,
        db_session=db_session,
    ).reranked_sections

    return GptSearchResponse(
        matching_document_chunks=[
            GptDocChunk(
                title=section.center_chunk.semantic_identifier,
                content=section.center_chunk.content,
                source_type=section.center_chunk.source_type,
                link=(
                    section.center_chunk.source_links.get(0, "")
                    if section.center_chunk.source_links
                    else ""
                ),
                metadata=section.center_chunk.metadata,
                document_age=(
                    time_ago(section.center_chunk.updated_at)
                    if section.center_chunk.updated_at
                    else "Unknown"
                ),
            )
            for section in top_sections
        ],
    )
