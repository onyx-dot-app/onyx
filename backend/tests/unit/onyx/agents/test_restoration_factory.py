"""Rebuild feature configuration and resources without replacing saved conversation state."""

from collections.abc import Callable
from functools import partial
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import JsonValue

from onyx.agents.agent_coordination import MAX_CHILD_DEPTH
from onyx.agents.models import (
    AgentState,
    AgentStep,
    ExecutionCheckpoint,
    RunProgress,
    RunState,
    RunStatus,
    StepInput,
    ToolCallContext,
)
from onyx.agents.runtime import Agent
from onyx.agents.tool_execution import STOPPED_CALL_MESSAGE
from onyx.agents.tools import (
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolInvocation,
)
from onyx.chat.agent import ChatAgent
from onyx.chat.models import PersonaPromptConfig
from onyx.chat.restoration import restore_chat_agent
from onyx.context.models import UserInfo, UserMemoryContext
from onyx.db.models import User
from onyx.deep_research.agent import DeepResearchAgent
from onyx.deep_research.research_agent import ResearchAgent
from onyx.file_store.models import ChatFileType, ChatLoadedFile, ExtractedContextFiles
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import LLM
from onyx.llm.model_capabilities import ToolFamily
from onyx.llm.model_response import Delta
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    ImageContentPart,
    ReasoningEffort,
    TextContent,
    ToolCall,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.skills.models import ChatSkill
from onyx.tools.constants import EXEC_TOOL_NAME, WAIT_TOOL_NAME
from onyx.tools.interface import Tool
from onyx.tools.models import CapabilityEntry, ToolContext
from onyx.tools.tool_implementations.code_mode.shapes import CODE_MODE_SHAPES
from onyx.tools.tool_implementations.question.models import QUESTION_TOOL_NAME
from onyx.tools.tool_implementations.question.question_tool import QuestionTool
from onyx.tools.tool_implementations.skills.skill_tools import (
    SkillsListTool,
    SkillsReadTool,
)
from tests.unit.onyx.agents.fakes import (
    EchoTool,
    FakeModelClient,
    ScriptedLLM,
    run_agent,
)
from tests.unit.onyx.tools.code_mode.fakes import FakeTool

PROJECT_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n"


def feature(
    name: str, llm: LLM, context: AgentState
) -> ChatAgent | ResearchAgent | DeepResearchAgent:
    if name == "chat":
        chat = ChatAgent(
            messages=context.messages,
            tools=[EchoTool()],
            preferred_tool=CapabilityEntry(tool_id=1),
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
                step_limit=3,
                feature_state=state.model_dump(mode="json"),
            ),
        ),
    )
    checkpoint = ExecutionCheckpoint.model_validate_json(checkpoint.model_dump_json())
    saved = checkpoint.model_copy(deep=True)
    if name == "chat":
        monkeypatch.setattr(
            "onyx.llm.factory.get_llm_tokenizer_encode_func",
            lambda _model: pytest.fail(
                "Restored chat loaded a tokenizer for telemetry"
            ),
        )
    rebuilt = restore_chat_agent(
        checkpoint,
        0,
        llm=llm,
        tools=[EchoTool()] if name == "chat" else [],
        user_identity=None,
        subagent_factory=lambda _depth: pytest.fail("No agent tools"),
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
        retained = next(
            msg for msg in request.messages if msg.text == "Retained conversation"
        )
        assert retained.estimated_tokens == 6
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


def test_restore_drops_an_old_preferred_tool_id_that_no_tool_offers() -> None:
    llm = FakeModelClient(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="done")])
    )
    original = feature("chat", llm, AgentState())
    state = original.capture_state().model_dump(mode="json")
    del state["preferred_tool"]
    # An MCP tool id from a run saved before tool options; MCP tools have no id now.
    state["preferred_tool_id"] = 999
    checkpoint = ExecutionCheckpoint(
        agent_state=original.state,
        run_state=RunState(
            run_id="legacy-run",
            agent_id=original.id,
            status=RunStatus.SUSPENDED,
            steps=[],
            progress=RunProgress(step_limit=3, feature_state=state),
        ),
    )
    rebuilt = restore_chat_agent(
        checkpoint,
        0,
        llm=llm,
        tools=[EchoTool()],
        user_identity=None,
        subagent_factory=lambda _depth: pytest.fail("No agent tools"),
    )
    assert isinstance(rebuilt, ChatAgent)
    rebuilt.restore_state(state)
    assert rebuilt.preferred_tool is None
    rebuilt._prepare_step(
        StepInput(
            history=[UserMessage(content="Question")],
            input_messages=[],
            messages=[],
            step=AgentStep(index=0, limit=2),
        )
    )


def test_factory_rejects_checkpoint_without_supported_feature_state() -> None:
    checkpoint = ExecutionCheckpoint(
        agent_state=AgentState(),
        run_state=RunState(
            run_id="unsupported-run",
            agent_id="unsupported-agent",
            status=RunStatus.SUSPENDED,
            steps=[],
            progress=RunProgress(step_limit=3),
        ),
    )
    llm = FakeModelClient(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="done")])
    )
    with pytest.raises(ValueError, match="no supported chat feature state"):
        restore_chat_agent(
            checkpoint,
            0,
            llm=llm,
            tools=[],
            user_identity=None,
            subagent_factory=lambda _depth: pytest.fail("No agent tools"),
        )


def _offered(llm: ScriptedLLM) -> tuple[list[str], ToolChoiceOptions, str]:
    [request] = llm.requests
    return (
        [tool["function"]["name"] for tool in request["tools"]],
        request["tool_choice"],
        str(request),
    )


def _chat_agent(
    llm: ScriptedLLM,
    *,
    code_mode: bool = False,
    tools: list[Tool] | None = None,
    create_subagent: Callable[[], Agent] | None = None,
) -> ChatAgent:
    return ChatAgent(
        create_subagent=create_subagent,
        messages=[],
        tools=tools or [EchoTool()],
        code_mode=code_mode,
        custom_agent_prompt=None,
        base_system_prompt="Base instructions",
        context_files=ExtractedContextFiles(
            file_texts=[],
            image_files=[],
            use_as_search_filter=False,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=None,
        ),
        persona=None,
        user_memory_context=None,
        llm=llm,
        preferred_tool=CapabilityEntry(tool_id=EchoTool().id),
        agent_id="retained-agent",
    )


def _suspended(agent: Agent, state: dict[str, JsonValue]) -> ExecutionCheckpoint:
    return ExecutionCheckpoint(
        agent_state=agent.state,
        run_state=RunState(
            run_id="suspended-run",
            agent_id=agent.id,
            status=RunStatus.SUSPENDED,
            steps=[],
            # The suspended step declared the agent's tools.
            progress=RunProgress(
                step_limit=3,
                tools=[tool.definition for tool in agent.tools],
                feature_state=state,
            ),
        ),
    )


_CODE_MODE_ECHO = "tools.echo (a function in `exec` programs)"


@pytest.mark.parametrize(
    ("saved_code_mode", "offered", "preferred"),
    [
        # Code mode names the preferred tool as a function of its programs.
        (True, [EXEC_TOOL_NAME, WAIT_TOOL_NAME], _CODE_MODE_ECHO),
        (False, [EchoTool().name], EchoTool().name),
    ],
)
def test_restored_chat_keeps_the_saved_code_mode(
    saved_code_mode: bool,
    offered: list[str],
    preferred: str,
) -> None:
    # Restoration reads only the saved state, never the deployment setting.
    llm = ScriptedLLM([Delta(content="done")])
    original = _chat_agent(
        llm, code_mode=saved_code_mode, create_subagent=lambda: _chat_agent(llm)
    )
    state = original.capture_state().model_dump(mode="json")
    rebuilt = restore_chat_agent(
        _suspended(original, state),
        0,
        llm=llm,
        tools=[EchoTool()],
        user_identity=None,
        subagent_factory=lambda _depth: lambda: _chat_agent(llm),
    )
    assert isinstance(rebuilt, ChatAgent)
    assert (rebuilt.code_cells is not None) == saved_code_mode
    rebuilt.restore_state(state)
    run_agent(rebuilt, max_steps=3, messages=[UserMessage(content="Go")])
    names, choice, request_text = _offered(llm)
    assert names == [
        *offered,
        "spawn_agent",
        "list_agents",
        "interrupt_agent",
        "send_message",
        "wait_agents",
    ]
    assert choice == ToolChoiceOptions.AUTO
    assert f"selected these operations for this request: {preferred}." in request_text


@pytest.mark.parametrize(
    ("saved", "active"),
    [
        (ToolFamily.OPENAI, ToolFamily.CLAUDE),
        (ToolFamily.CLAUDE, ToolFamily.OPENAI),
    ],
)
def test_a_program_parked_under_one_family_ends_truthfully_under_the_other(
    saved: ToolFamily, active: ToolFamily
) -> None:
    """A run continues on the active model's tool shapes. The parked program's
    call, whose tool that shape does not have, says that its calls may have
    had effects; the run then completes."""
    sent: list[JsonValue] = []
    saved_shape, active_shape = CODE_MODE_SHAPES[saved], CODE_MODE_SHAPES[active]
    program = ToolCall(
        id="program",
        name=saved_shape.run_name,
        arguments={"code": 'print("before")\nprint(await tools.send(value="x"))'},
    )

    def send(invocation: ToolInvocation, _context: ToolContext) -> ToolResult:
        sent.append(invocation.arguments["value"])
        return ToolResult(content="sent")

    def first(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        return AssistantMessage(content=[program])

    results: list[str] = []

    def second(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        results.extend(
            message.text
            for message in request.messages
            if isinstance(message, ToolResultMessage)
        )
        return AssistantMessage(content=[TextContent(text="done")])

    def question(response_id: int, name: str) -> QuestionTool:
        return QuestionTool(
            name, tenant_id="tenant", chat_session_id=uuid4(), response_id=response_id
        )

    def ask_for_send(context: ToolCallContext) -> PendingToolInput | None:
        if context.call.name != "send":
            return None
        return PendingToolInput(
            request_id="send-approval", prompt="Send?", mode=InputMode.EXECUTE
        )

    original = ChatAgent(
        messages=[],
        tools=[FakeTool("send", send)],
        code_mode=True,
        custom_agent_prompt=None,
        base_system_prompt="Base instructions",
        context_files=ExtractedContextFiles(
            file_texts=[],
            image_files=[],
            use_as_search_filter=False,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=None,
        ),
        persona=None,
        user_memory_context=None,
        llm=FakeModelClient(first, saved),
        agent_id="parked-agent",
        question_tool=partial(question, 1),
    )
    original.before_tool_call = ask_for_send
    run = original.start(max_steps=3, messages=[UserMessage(content="Send")])
    state = run.wait_until_settled(timeout=20)
    assert state.status == RunStatus.SUSPENDED, state.failure
    assert run.wait_for_idle(10)
    captured = run.capture().model_dump(mode="json")
    # A chat run's id is its response's message id.
    checkpoint = ExecutionCheckpoint.model_validate(
        {**captured, "run_state": {**captured["run_state"], "run_id": "7"}}
    )

    rebuilt = restore_chat_agent(
        checkpoint,
        0,
        llm=FakeModelClient(second, active),
        tools=[FakeTool("send", send)],
        user_identity=None,
        subagent_factory=lambda _depth: pytest.fail("No agent tools"),
        question_tool=question,
    )
    assert isinstance(rebuilt, ChatAgent)
    assert {tool.name for tool in rebuilt.application_tools} == {
        active_shape.run_name,
        active_shape.wait_name,
        QUESTION_TOOL_NAME[active],
    }
    resumed = rebuilt.resume(
        checkpoint.run_state,
        answers=[
            HumanToolAnswer(request_id="send-approval", decision=InputDecision.APPROVE)
        ],
    )
    assert resumed.result(timeout=20).output.text == "done"
    assert resumed.wait_for_idle(10)
    assert sent == []
    assert results == [STOPPED_CALL_MESSAGE]


@pytest.fixture
def _user_skills(monkeypatch: pytest.MonkeyPatch) -> User:
    """A user whose current skills are one skill, as the skill tools and
    the catalog read them."""
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.skills.skill_tools.get_session_with_current_tenant",
        MagicMock(),
    )
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.skills.skill_tools.list_chat_skills",
        lambda _session, _user, **_kwargs: [
            ChatSkill(name="triage", description="Sort.", version_id=uuid4())
        ],
    )
    return User(id=uuid4())


def test_restored_chat_offers_the_skill_tools_once(_user_skills: User) -> None:
    # Restoration receives the turn's configured tools, skill tools included.
    llm = ScriptedLLM([Delta(content="done")])
    original = _chat_agent(
        llm,
        tools=[
            EchoTool(),
            SkillsListTool(_user_skills, with_sandbox=False),
            SkillsReadTool(_user_skills, with_sandbox=False),
        ],
    )
    state = original.capture_state().model_dump(mode="json")

    rebuilt = restore_chat_agent(
        _suspended(original, state),
        0,
        llm=llm,
        tools=original.configured_tools,
        user_identity=None,
        subagent_factory=lambda _depth: pytest.fail("No agent tools"),
    )
    assert isinstance(rebuilt, ChatAgent)
    rebuilt.restore_state(state)
    run_agent(rebuilt, max_steps=3, messages=[UserMessage(content="Go")])

    names, _, _ = _offered(llm)
    assert names == [EchoTool().name, "skills_list", "skills_read"]


def test_code_mode_offers_the_skill_tools_as_program_functions(
    _user_skills: User,
) -> None:
    llm = ScriptedLLM([Delta(content="done")])
    agent = _chat_agent(
        llm,
        code_mode=True,
        tools=[
            SkillsListTool(_user_skills, with_sandbox=False),
            SkillsReadTool(_user_skills, with_sandbox=False),
        ],
    )
    run_agent(agent, max_steps=3, messages=[UserMessage(content="Go")])

    names, _, request = _offered(llm)
    assert names == ["exec", "wait"]
    # The catalog names the functions that programs call
    assert "- triage: Sort." in request
    assert "`tools.skills_read`" in request
    assert "`tools.skills_list`" in request


def test_restored_deep_research_offers_the_skill_tools_like_the_original(
    _user_skills: User,
) -> None:
    llm = ScriptedLLM([])
    original = DeepResearchAgent(
        messages=[],
        allowed_tools=[
            SkillsListTool(_user_skills, with_sandbox=False),
            SkillsReadTool(_user_skills, with_sandbox=False),
        ],
        llm=llm,
        token_counter=len,
        user_identity=None,
        language_section="",
        reasoning_effort=ReasoningEffort.LOW,
        all_injected_file_metadata={},
        skip_clarification=True,
    )

    rebuilt = restore_chat_agent(
        _suspended(original, original.capture_state().model_dump(mode="json")),
        0,
        llm=llm,
        tools=original.application_tools,
        user_identity=None,
        subagent_factory=lambda _depth: pytest.fail("No agent tools"),
    )

    names = [tool.definition.name for tool in original.tools]
    assert {"skills_list", "skills_read"} <= set(names)
    assert [tool.definition for tool in rebuilt.tools] == [
        tool.definition for tool in original.tools
    ]
    assert isinstance(rebuilt, DeepResearchAgent)
    for agent in (original, rebuilt):
        assert agent.skills_catalog_message is not None
        assert "- triage: Sort." in agent.skills_catalog_message.text


@pytest.mark.parametrize(
    ("agent_tools", "depth"),
    [(False, 0), (True, 0), (True, 1), (True, MAX_CHILD_DEPTH)],
)
def test_restored_chat_keeps_its_agent_tools_at_its_depth(
    agent_tools: bool, depth: int
) -> None:
    # A root whose client offered no agent tools resumes without them, and a
    # child's children are one level deeper; at the limit it cannot spawn.
    llm = ScriptedLLM([Delta(content="done")])
    original = _chat_agent(
        llm, create_subagent=(lambda: _chat_agent(llm)) if agent_tools else None
    )
    state = original.capture_state().model_dump(mode="json")
    child_depths: list[int] = []

    def subagent_factory(child_depth: int) -> Callable[[], Agent]:
        child_depths.append(child_depth)
        return lambda: _chat_agent(llm)

    rebuilt = restore_chat_agent(
        _suspended(original, state),
        depth,
        llm=llm,
        tools=[EchoTool()],
        user_identity=None,
        subagent_factory=subagent_factory,
    )
    names = {tool.name for tool in rebuilt.tools}
    assert ("list_agents" in names) == agent_tools
    assert ("spawn_agent" in names) == (agent_tools and depth < MAX_CHILD_DEPTH)
    assert child_depths == ([depth + 1] if agent_tools else [])
