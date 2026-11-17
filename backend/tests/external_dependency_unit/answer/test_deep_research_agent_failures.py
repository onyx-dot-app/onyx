import threading
from typing import Any
from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.agents.agent_coordination import _ToolControl
from onyx.agents.runtime import Agent
from onyx.agents.tools import SpawnResult
from onyx.chat.models import AnswerStreamPart
from onyx.chat.process_message import handle_stream_message_objects
from onyx.db.chat import get_chat_messages_by_session
from onyx.db.tools import get_tool_by_name
from onyx.deep_research.tool_definitions import (
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TOOL_NAME,
)
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolChoiceOptions,
    ToolResultMessage,
)
from onyx.server.query_and_chat.models import MessageResponseIDInfo, SendMessageRequest
from onyx.server.query_and_chat.streaming_models import StreamingError
from tests.common.models import CI_OPENAI_MODEL
from tests.external_dependency_unit.answer.stream_test_utils import create_chat_session
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.unit.onyx.agents.fakes import FakeModelClient

FAST_TASK = "Research the alpha market"
SLOW_TASK = "Research the beta market"
FAST_CALL_ID = "call_research_fast"
SLOW_CALL_ID = "call_research_slow"
RESEARCH_PLAN = "1. Research alpha\n2. Research beta"
FAST_REPORT = "Alpha market findings."
FINAL_REPORT = "Final report on alpha."
SLOW_TASK_TIMEOUT_SECONDS = 1
_spawn_agent = _ToolControl.spawn_agent


def _spawn_with_slow_task_deadline(
    control: _ToolControl, agent: Agent, **kwargs: Any
) -> SpawnResult:
    """Give only the slow task a deadline, so a loaded machine cannot time out the fast one."""
    kwargs["total_timeout_s"] = (
        SLOW_TASK_TIMEOUT_SECONDS if kwargs["description"] == SLOW_TASK else None
    )
    return _spawn_agent(control, agent, **kwargs)


class RecordedRequest:
    def __init__(self, request: GenerationRequest) -> None:
        self.messages = request.messages
        self.tool_names = {tool.name for tool in request.tools}

    def tool_responses(self) -> dict[str, str]:
        return {
            message.tool_call_id: message.text
            for message in self.messages
            if isinstance(message, ToolResultMessage)
        }

    def mentions(self, text: str) -> bool:
        return any(text in message.text for message in self.messages)


class DeepResearchScriptLLM(FakeModelClient):
    """Exercise concurrent research and cancellation without provider calls."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: list[RecordedRequest] = []
        self.slow_task_cancelled = threading.Event()
        super().__init__(self._reply)

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai",
            model_name=CI_OPENAI_MODEL,
            max_input_tokens=1_000_000_000,
            temperature=1.0,
        )

    def _reply(
        self, request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        recorded = RecordedRequest(request)
        with self._lock:
            self.requests.append(recorded)
        if RESEARCH_AGENT_TOOL_NAME in recorded.tool_names:
            if recorded.tool_responses():
                return AssistantMessage(
                    content=[
                        ToolCall(
                            id="orchestrator_report",
                            name=GENERATE_REPORT_TOOL_NAME,
                            arguments={},
                        )
                    ]
                )
            return AssistantMessage(
                content=[
                    ToolCall(
                        id=call_id,
                        name=RESEARCH_AGENT_TOOL_NAME,
                        arguments={"task": task},
                    )
                    for call_id, task in [
                        (FAST_CALL_ID, FAST_TASK),
                        (SLOW_CALL_ID, SLOW_TASK),
                    ]
                ]
            )
        if recorded.mentions(SLOW_TASK):
            # Only the deadline ends this call; any other failure leaves it unset.
            with signal.on_cancel(self.slow_task_cancelled.set):
                self.slow_task_cancelled.wait(10)
            signal.check()
        if (
            GENERATE_REPORT_TOOL_NAME in recorded.tool_names
            and request.options.tool_choice != ToolChoiceOptions.NONE
        ):
            return AssistantMessage(
                content=[
                    ToolCall(
                        id="child_report", name=GENERATE_REPORT_TOOL_NAME, arguments={}
                    )
                ]
            )
        text = (
            FAST_REPORT
            if recorded.mentions(FAST_TASK)
            else FINAL_REPORT
            if recorded.tool_responses()
            else RESEARCH_PLAN
        )
        return AssistantMessage(content=[TextContent(text=text)])


def test_timed_out_research_agent_is_a_failed_call(
    db_session: Session,
    make_test_user: MakeTestUser,
    full_deployment_setup: None,  # noqa: ARG001
    default_llm_provider: None,  # noqa: ARG001
    mock_external_deps: None,  # noqa: ARG001
) -> None:
    user = make_test_user("dr_research_agent_timeout")
    chat_session = create_chat_session(db_session=db_session, user=user)

    llm = DeepResearchScriptLLM()

    request = SendMessageRequest(
        message="Compare the alpha and beta markets",
        chat_session_id=chat_session.id,
        deep_research=True,
    )

    with (
        patch("onyx.chat.process_message.get_llm_for_persona", return_value=llm),
        patch("onyx.chat.execution.SKIP_DEEP_RESEARCH_CLARIFICATION", True),
        patch.object(_ToolControl, "spawn_agent", _spawn_with_slow_task_deadline),
    ):
        parts: list[AnswerStreamPart] = list(
            handle_stream_message_objects(new_msg_req=request, user=user)
        )

    errors = [part for part in parts if isinstance(part, StreamingError)]
    assert not errors, errors
    assert llm.slow_task_cancelled.is_set(), "The research deadline did not cancel"

    # The orchestrator's next request answers the timed-out call with the failure message.
    orchestrator_follow_ups = [
        recorded.tool_responses()
        for recorded in llm.requests
        if RESEARCH_AGENT_TOOL_NAME in recorded.tool_names
        and SLOW_CALL_ID in recorded.tool_responses()
    ]
    assert orchestrator_follow_ups, (
        "No orchestrator request answered the timed-out call"
    )
    assert orchestrator_follow_ups[0] == {
        FAST_CALL_ID: FAST_REPORT,
        SLOW_CALL_ID: "Research failed. Continue with other sources or try a different task.",
    }

    # Both calls retain their result, including the recoverable failure.
    [id_info] = [part for part in parts if isinstance(part, MessageResponseIDInfo)]
    db_session.expire_all()
    messages = get_chat_messages_by_session(
        chat_session_id=chat_session.id,
        user_id=user.id,
        db_session=db_session,
    )
    [assistant_message] = [
        message
        for message in messages
        if message.id == id_info.reserved_assistant_message_id
    ]
    assert assistant_message.message == FINAL_REPORT

    research_agent_tool_id = get_tool_by_name(
        tool_name=RESEARCH_AGENT_TOOL_NAME, db_session=db_session
    ).id
    # The relationship has no order; history replay sorts the same way.
    saved_research_calls = sorted(
        (
            tool_call
            for tool_call in assistant_message.tool_calls or []
            if tool_call.tool_id == research_agent_tool_id
        ),
        key=lambda call: (call.turn_number, call.tab_index, call.id),
    )
    assert [
        (tool_call.tool_call_id, tool_call.tool_call_response)
        for tool_call in saved_research_calls
    ] == [
        (FAST_CALL_ID, FAST_REPORT),
        (
            SLOW_CALL_ID,
            "Research failed. Continue with other sources or try a different task.",
        ),
    ]
