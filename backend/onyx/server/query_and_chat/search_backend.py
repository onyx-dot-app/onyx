import json
from collections.abc import Callable
from collections.abc import Generator

from fastapi import APIRouter
from fastapi import Depends
from fastapi.responses import StreamingResponse

from onyx.auth.users import current_chat_accessible_user
from onyx.chat.process_message import stream_search_results
from onyx.db.models import User
from onyx.server.query_and_chat.chat_utils import is_connected
from onyx.server.query_and_chat.models import SearchRequest
from onyx.utils.logger import setup_logger


logger = setup_logger()
router = APIRouter(prefix="/search")


@router.post("/send-query")
def handle_new_search(
    search_request: SearchRequest,
    user: User | None = Depends(current_chat_accessible_user),
    is_connected_func: Callable[[], bool] = Depends(is_connected),
) -> StreamingResponse:
    def stream_generator() -> Generator[str, None, None]:
        try:
            for packet in stream_search_results(
                api_search_request=search_request,
                user=user,
            ):
                yield packet

        except Exception as e:
            logger.exception("Error in chat message streaming")
            yield json.dumps({"error": str(e)})

        finally:
            logger.debug("Stream generator finished")

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@router.get("/suggestions")
def get_search_suggestions(
    user: User | None = Depends(current_chat_accessible_user),
) -> list[str]:
    """Get search suggestions for the user"""

    # Static for now.
    return [
        "How to configure authentication?",
        "What are the best practices for deployment?",
        "How to integrate with external APIs?",
        "Troubleshooting common issues",
        "Performance optimization tips",
        "Security best practices",
        "Database migration guide",
        "API documentation examples",
    ]
