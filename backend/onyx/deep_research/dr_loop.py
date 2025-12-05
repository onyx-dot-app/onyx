from collections.abc import Callable

from sqlalchemy.orm import Session

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import Emitter
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import ExtractedProjectFiles
from onyx.db.models import Persona
from onyx.llm.interfaces import LLM
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger

logger = setup_logger()


def run_deep_research_llm_loop(
    emitter: Emitter,
    state_container: ChatStateContainer,
    simple_chat_history: list[ChatMessageSimple],
    tools: list[Tool],
    custom_agent_prompt: str | None,
    project_files: ExtractedProjectFiles,
    persona: Persona | None,
    memories: list[str] | None,
    llm: LLM,
    token_counter: Callable[[str], int],
    db_session: Session,
    forced_tool_id: int | None = None,
) -> None:
    raise NotImplementedError("Deep research loop not implemented")
