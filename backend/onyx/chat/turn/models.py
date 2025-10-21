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
from agents import Model
from agents import ModelSettings
from agents import WebSearchTool
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
    llm_model: Model
    model_settings: ModelSettings
    llm: LLM
    db_session: Session
    tools: Sequence[FunctionTool]
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
    should_cite_documents: bool = False
