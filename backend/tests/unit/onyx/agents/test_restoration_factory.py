"""Rebuild feature configuration and resources without replacing saved conversation state."""

import pytest

from onyx.agents.models import (
    AgentState,
    AgentStep,
    ExecutionCheckpoint,
    RunProgress,
    RunState,
    RunStatus,
    StepInput,
)
from onyx.chat.agent import ChatAgent
from onyx.chat.models import PersonaPromptConfig
from onyx.chat.restoration import restore_chat_agent
from onyx.context.models import UserInfo, UserMemoryContext
from onyx.deep_research.agent import DeepResearchAgent
from onyx.deep_research.research_agent import ResearchAgent
from onyx.file_store.models import ChatFileType, ChatLoadedFile, ExtractedContextFiles
from onyx.llm.interfaces import LLM
from onyx.llm.models import (
    AssistantMessage,
    ImageContentPart,
    ReasoningEffort,
    TextContent,
    UserMessage,
)
from tests.unit.onyx.agents.fakes import EchoTool, FakeModelClient

PROJECT_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n"


def feature(
    name: str, llm: LLM, context: AgentState
) -> ChatAgent | ResearchAgent | DeepResearchAgent:
    if name == "chat":
        chat = ChatAgent(
            messages=context.messages,
            tools=[EchoTool()],
            preferred_tool_id=1,
            custom_agent_prompt="Hello {{user.name}}",
            additional_context="Use the current request context.",
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
            reminders_enabled=False,
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
            additional_context="Use the current research context.",
            context_files=ExtractedContextFiles(
                file_texts=[],
                image_files=[
                    ChatLoadedFile(
                        file_id="project-image",
                        filename="project.png",
                        content=PROJECT_IMAGE_BYTES,
                        file_type=ChatFileType.IMAGE,
                        content_text=None,
                        token_count=100,
                    )
                ],
                use_as_search_filter=False,
                total_token_count=100,
                file_metadata=[],
                uncapped_token_count=None,
            ),
            agent_id="retained-agent",
        )
    raise ValueError(f"Unknown feature: {name}")


@pytest.mark.parametrize("name", ["chat", "research", "deep_research"])
def test_factory_rebuilds_feature_and_preserves_saved_context(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def read_image(file_id: str) -> bytes:
        assert file_id == "project-image"
        return PROJECT_IMAGE_BYTES

    monkeypatch.setattr("onyx.tools.file_snapshot.read_checkpoint_file", read_image)
    monkeypatch.setattr(
        "onyx.chat.prompt_formatting.model_supports_image_input", lambda *_args: True
    )
    llm = FakeModelClient(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="done")])
    )
    context = AgentState(messages=[UserMessage(content="Retained conversation")])
    original = feature(name, llm, context)
    context = original.state
    state = original.capture_state()
    checkpoint = ExecutionCheckpoint(
        agent_state=context,
        run_state=RunState(
            run_id="suspended-run",
            agent_id=original.id,
            status=RunStatus.SUSPENDED,
            steps=[],
            progress=RunProgress(
                tool_configuration_digest="test-tool-configuration",
                step_limit=3,
                feature_state=state.model_dump(mode="json"),
            ),
        ),
    )
    checkpoint = ExecutionCheckpoint.model_validate_json(checkpoint.model_dump_json())
    saved = checkpoint.model_copy(deep=True)
    rebuilt = restore_chat_agent(
        checkpoint,
        llm=llm,
        tools=[EchoTool()] if name == "chat" else [],
        user_identity=None,
    )
    assert rebuilt is not original
    assert rebuilt.id == original.id
    assert rebuilt.state == context
    assert isinstance(rebuilt, (ChatAgent, ResearchAgent, DeepResearchAgent))
    assert type(rebuilt) is type(original)
    rebuilt.restore_state(state.model_dump(mode="json"))
    restored = rebuilt.capture_state()
    assert restored.model_dump(exclude={"elapsed_seconds"}) == state.model_dump(
        exclude={"elapsed_seconds"}
    )
    if isinstance(original, ChatAgent):
        assert isinstance(rebuilt, ChatAgent)
        assert rebuilt.custom_agent_prompt == original.custom_agent_prompt
        assert rebuilt.persona == original.persona
        prepared = rebuilt._prepare_step(
            StepInput(
                history=context.messages,
                input_messages=[],
                messages=[],
                step=AgentStep(index=0, limit=2),
            )
        )
        request = prepared.generation_request(context.messages)
        assert request.messages[0].text.startswith("Help {{user.role}}")
        assert (
            "The user selected these operations for this request: echo."
            in request.messages[-1].text
        )
        assert not request.messages[-1].cacheable
    elif isinstance(rebuilt, DeepResearchAgent):
        prepared = rebuilt._prepare_step(
            StepInput(
                history=context.messages,
                input_messages=[],
                messages=[],
                step=AgentStep(index=0, limit=2),
            )
        )
        request = prepared.generation_request(context.messages)
        project = request.messages[1]
        assert isinstance(project, UserMessage) and isinstance(project.content, list)
        assert any(isinstance(part, ImageContentPart) for part in project.content)
        assert project.cacheable
        request_context = request.messages[-2]
        assert "Use the current research context." in request_context.text
        assert not request_context.cacheable
    assert checkpoint == saved
    message = checkpoint.agent_state.messages[0]
    assert isinstance(message, UserMessage)
    message.content = "Changed after restoration"
    assert rebuilt.state == saved.agent_state


def test_factory_rejects_checkpoint_without_supported_feature_state() -> None:
    checkpoint = ExecutionCheckpoint(
        agent_state=AgentState(),
        run_state=RunState(
            run_id="unsupported-run",
            agent_id="coding-agent",
            status=RunStatus.SUSPENDED,
            steps=[],
            progress=RunProgress(
                tool_configuration_digest="test-tool-configuration", step_limit=3
            ),
        ),
    )
    llm = FakeModelClient(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="done")])
    )
    with pytest.raises(ValueError, match="no supported chat feature state"):
        restore_chat_agent(checkpoint, llm=llm, tools=[], user_identity=None)
