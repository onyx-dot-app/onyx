import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from agents import CodeInterpreterTool
from agents import ComputerTool
from agents import FileSearchTool
from agents import FunctionTool
from agents import HostedMCPTool
from agents import ImageGenerationTool as AgentsImageGenerationTool
from agents import LocalShellTool
from agents import WebSearchTool
from pydantic import BaseModel
from redis.client import Redis
from sqlalchemy.orm import Session

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.chat.models import PromptConfig
from onyx.chat.turn.infra.emitter import Emitter
from onyx.context.search.models import InferenceSection
from onyx.db.models import User
from onyx.llm.interfaces import LLM
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.tools.tool import Tool

# Type alias for all tool types accepted by the Agent
AgentToolType = (
    FunctionTool
    | FileSearchTool
    | WebSearchTool
    | ComputerTool
    | HostedMCPTool
    | LocalShellTool
    | AgentsImageGenerationTool
    | CodeInterpreterTool
)


@dataclass
class ChatTurnDependencies:
    llm: LLM
    db_session: Session
    tools: Sequence[Tool]
    redis_client: Redis
    emitter: Emitter
    user_or_none: User | None
    prompt_config: PromptConfig


class FetchedDocumentCacheEntry(BaseModel):
    inference_section: InferenceSection
    document_citation_number: int


@dataclass
class ChatTurnContext:
    """Context class to hold search tool and other dependencies"""

    chat_session_id: UUID
    message_id: int
    research_type: ResearchType
    run_dependencies: ChatTurnDependencies
    current_run_step: int = 0
    iteration_instructions: list[IterationInstructions] = dataclasses.field(
        default_factory=list
    )
    global_iteration_responses: list[IterationAnswer] = dataclasses.field(
        default_factory=list
    )
    should_cite_documents: bool = False
    documents_processed_by_citation_context_handler: int = 0
    tool_calls_processed_by_citation_context_handler: int = 0
    fetched_documents_cache: dict[str, FetchedDocumentCacheEntry] = dataclasses.field(
        default_factory=dict
    )
    citations: list[CitationInfo] = dataclasses.field(default_factory=list)

    # Used to ignore packets that are streamed back by Agents SDK, but should
    # not be emitted to the frontend (e.g. out of order packets)
    # TODO: remove this once Agents SDK fixes the bug with Anthropic reasoning
    current_output_index: int | None = None
