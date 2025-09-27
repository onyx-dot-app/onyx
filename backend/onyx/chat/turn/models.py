from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.chat.turn.infra.chat_turn_event_stream import Emitter
from onyx.llm.interfaces import LLM
from onyx.tools.tool_implementations.search.search_tool import SearchTool


@dataclass
class DependenciesToMaybeRemove:
    chat_session_id: UUID
    message_id: int
    research_type: ResearchType


@dataclass
class RunDependencies:
    llm: LLM
    db_session: Session
    emitter: Emitter | None = None
    search_tool: SearchTool | None = None
    dependencies_to_maybe_remove: DependenciesToMaybeRemove | None = None


@dataclass
class MyContext:
    """Context class to hold search tool and other dependencies"""

    run_dependencies: RunDependencies | None = None
    needs_compaction: bool = False
    current_run_step: int = 0
    # TODO: Figure out a cleaner way to persist information.
    aggregated_context: AggregatedDRContext | None = None
    iteration_instructions: list[IterationInstructions] | None = None
