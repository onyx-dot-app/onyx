"""Rebuild feature configuration and resources without replacing saved conversation state."""

import pytest

from onyx.agents.execution_records import RunStatus
from onyx.agents.models import (
    AgentState,
    ExecutionCheckpoint,
    RunProgress,
    RunState,
)
from onyx.chat.agent import ChatAgent
from onyx.chat.context import ChatReminders
from onyx.chat.models import PersonaPromptConfig
from onyx.chat.restoration import restore_chat_agent
from onyx.db.memory import UserInfo, UserMemoryContext
from onyx.deep_research.agent import DeepResearchAgent
from onyx.deep_research.research_agent import ResearchAgent
from onyx.file_store.models import ExtractedContextFiles
from onyx.llm.interfaces import LLM
from onyx.llm.models import AssistantMessage, ReasoningEffort, TextContent, UserMessage
from tests.unit.onyx.agents.fakes import FakeModelClient


def feature(
    name: str, llm: LLM, context: AgentState
) -> ChatAgent | ResearchAgent | DeepResearchAgent:
    if name == "chat":
        chat = ChatAgent(
            messages=context.messages,
            tools=[],
            custom_agent_prompt="Hello {{user.name}}",
            base_system_prompt="Base instructions",
            context_files=ExtractedContextFiles(
                file_texts=[],
                image_files=[],
                use_as_search_filter=False,
                total_token_count=0,
                file_metadata=[],
                uncapped_token_count=None,
            ),
            persona=PersonaPromptConfig(
                system_prompt="Help {{user.name}}",
                task_prompt="Task instructions",
                datetime_aware=False,
                replace_base_system_prompt=True,
            ),
            user_memory_context=UserMemoryContext(
                user_info=UserInfo(
                    placeholder_values={
                        "name": "{{user.role}}",
                        "role": "Engineer",
                    }
                ),
            ),
            llm=llm,
            token_counter=len,
            reasoning_effort=ReasoningEffort.LOW,
            include_citations=False,
            inject_memories_in_prompt=False,
            reminders=ChatReminders(enabled=False),
            agent_id="retained-agent",
        )
        chat.has_called_search_tool = True
        return chat
    if name == "research":
        research = ResearchAgent(
            tools=[],
            llm=llm,
            token_counter=len,
            user_identity=None,
            language_section="Write in French",
            reasoning_effort=ReasoningEffort.LOW,
            messages=context.messages,
            agent_id="retained-agent",
        )
        research.citation_mapping = {7: "retained-source"}
        return research
    if name == "deep_research":
        return DeepResearchAgent(
            messages=context.messages,
            allowed_tools=[],
            llm=llm,
            token_counter=len,
            user_identity=None,
            language_section="Write in French",
            reasoning_effort=ReasoningEffort.LOW,
            all_injected_file_metadata={},
            skip_clarification=True,
            agent_id="retained-agent",
        )
    raise ValueError(f"Unknown feature: {name}")


@pytest.mark.parametrize("name", ["chat", "research", "deep_research"])
def test_factory_rebuilds_feature_and_preserves_saved_context(name: str) -> None:
    llm = FakeModelClient(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="done")])
    )
    context = AgentState(messages=[UserMessage(content="Retained conversation")])
    original = feature(name, llm, context)
    state = original.capture_state()
    checkpoint = ExecutionCheckpoint(
        agent_state=context,
        run_state=RunState(
            run_id="suspended-run",
            agent_id=original.agent.id,
            status=RunStatus.SUSPENDED,
            messages=[],
            progress=RunProgress(step_limit=3, feature_state=state),
        ),
    )
    saved = checkpoint.model_copy(deep=True)
    rebuilt = restore_chat_agent(checkpoint, llm=llm, tools=[], user_identity=None)
    assert rebuilt is not original.agent
    assert rebuilt.id == original.agent.id
    assert rebuilt.state == context
    assert rebuilt.restoration is not None
    assert type(rebuilt.restoration) is type(original)
    assert rebuilt.restoration is not original
    rebuilt.restoration.restore_state(state)
    restored = rebuilt.restoration.capture_state()
    assert restored.model_dump(exclude={"elapsed_seconds"}) == state.model_dump(
        exclude={"elapsed_seconds"}
    )
    if isinstance(original, ChatAgent):
        assert isinstance(rebuilt.restoration, ChatAgent)
        assert (
            rebuilt.restoration.context.custom_prompt == original.context.custom_prompt
        )
        assert (
            rebuilt.restoration.context.persona_system
            == original.context.persona_system
        )
        assert rebuilt.restoration.context.custom_prompt == "Hello {{user.role}}"
    assert checkpoint == saved


def test_factory_rejects_checkpoint_without_supported_feature_state() -> None:
    checkpoint = ExecutionCheckpoint(
        agent_state=AgentState(),
        run_state=RunState(
            run_id="unsupported-run",
            agent_id="coding-agent",
            status=RunStatus.SUSPENDED,
            messages=[],
            progress=RunProgress(step_limit=3),
        ),
    )
    llm = FakeModelClient(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="done")])
    )
    with pytest.raises(ValueError, match="no supported chat feature state"):
        restore_chat_agent(checkpoint, llm=llm, tools=[], user_identity=None)
