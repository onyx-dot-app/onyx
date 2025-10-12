import dataclasses
from dataclasses import dataclass
from uuid import UUID

from agents import FunctionTool
from agents import Model
from redis.client import Redis
from sqlalchemy.orm import Session

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.chat.turn.infra.emitter import Emitter
from onyx.llm.interfaces import LLM
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.okta_profile.okta_profile_tool import (
    OktaProfileTool,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool


@dataclass
class ChatTurnDependencies:
    llm_model: Model
    llm: LLM
    db_session: Session
    tools: list[FunctionTool]
    redis_client: Redis
    emitter: Emitter
    search_pipeline: SearchTool | None = None
    image_generation_tool: ImageGenerationTool | None = None
    okta_profile_tool: OktaProfileTool | None = None


@dataclass
class ChatTurnContext:
    """Context class to hold search tool and other dependencies"""

    chat_session_id: UUID
    message_id: int
    research_type: ResearchType
    run_dependencies: ChatTurnDependencies
    aggregated_context: AggregatedDRContext
    current_run_step: int = 0
    iteration_instructions: list[IterationInstructions] = dataclasses.field(
        default_factory=list
    )
    web_fetch_results: list[dict] = dataclasses.field(default_factory=list)
