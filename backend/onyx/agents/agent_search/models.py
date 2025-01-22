from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.context.search.models import SearchRequest
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.tools.tool_implementations.search.search_tool import SearchTool


@dataclass
class AgentSearchConfig:
    """
    Configuration for the Agent Search feature.
    """

    # The search request that was used to generate the Pro Search
    search_request: SearchRequest

    primary_llm: LLM
    fast_llm: LLM
    search_tool: SearchTool
    use_agentic_search: bool = True

    # For persisting agent search data
    chat_session_id: UUID | None = None

    # The message ID of the user message that triggered the Pro Search
    message_id: int | None = None

    # Whether to persistence data for the Pro Search (turned off for testing)
    use_persistence: bool = True

    # The database session for the Pro Search
    db_session: Session | None = None

    # Whether to perform initial search to inform decomposition
    perform_initial_search_path_decision: bool = True

    # Whether to perform initial search to inform decomposition
    perform_initial_search_decomposition: bool = True

    # Whether to allow creation of refinement questions (and entity extraction, etc.)
    allow_refinement: bool = True

    # Message history for the current chat session
    message_history: list[PreviousMessage] | None = None

    structured_response_format: dict | None = None


class AgentDocumentCitations(BaseModel):
    document_id: str
    document_title: str
    link: str
