"""
FastAPI router for Qdrant document search endpoints.
Provides real-time search-as-you-type functionality.
"""

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query

from onyx.auth.users import current_user
from onyx.db.models import User
from onyx.server.qdrant_search.models import QdrantSearchResponse
from onyx.server.qdrant_search.service import search_documents
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/qdrant")


@router.get("/search")
async def search_qdrant_documents(
    query: str = Query(..., min_length=1, description="Search query text"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of results"),
    _user: User | None = Depends(current_user),
) -> QdrantSearchResponse:
    """
    Search for documents in Qdrant using hybrid search (dense + sparse vectors).

    This endpoint is optimized for search-as-you-type functionality with:
    - Fast hybrid search using pre-computed embeddings
    - Sub-second response times
    - Relevance scoring using Distribution-Based Score Fusion

    Args:
        query: The search query text (minimum 1 character)
        limit: Maximum number of results to return (1-50, default 10)

    Returns:
        QdrantSearchResponse containing matching documents with scores
    """
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    logger.info(f"Search request: query='{query[:50]}...', limit={limit}")

    try:
        response = search_documents(query=query.strip(), limit=limit)
        logger.info(
            f"Search completed: {response.total_results} results for '{query[:50]}'"
        )
        return response

    except Exception as e:
        logger.error(f"Error in search endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Internal server error during search: {str(e)}"
        )
