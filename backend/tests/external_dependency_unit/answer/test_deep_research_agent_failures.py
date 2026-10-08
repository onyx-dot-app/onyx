import threading
from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.chat.models import AnswerStreamPart, StreamingError
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
    ToolResultMessage,
)
from onyx.server.query_and_chat.models import MessageResponseIDInfo, SendMessageRequest
from tests.external_dependency_unit.answer.conftest import ensure_default_llm_provider
from tests.external_dependency_unit.answer.stream_test_utils import create_chat_session
from tests.external_dependency_unit.conftest import create_test_user
from tests.unit.onyx.agents.fakes import FakeModelClient

FAST_TASK = "Research the alpha market"
SLOW_TASK = "Research the beta market"
FAST_CALL_ID = "call_research_fast"
SLOW_CALL_ID = "call_research_slow"
RESEARCH_PLAN = "1. Research alpha\n2. Research beta"
FAST_REPORT = "Alpha market findings."
FINAL_REPORT = "Final report on alpha."
TEST_TIMEOUT_SECONDS = 1


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
        super().__init__(self._reply)

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai",
            model_name="gpt-5-mini",
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
            cancelled = threading.Event()
            with signal.on_cancel(cancelled.set):
                if not cancelled.wait(10):
                    raise AssertionError("Research deadline did not cancel the child")
            signal.check()
        if GENERATE_REPORT_TOOL_NAME in recorded.tool_names:
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
    full_deployment_setup: None,  # noqa: ARG001
    mock_external_deps: None,  # noqa: ARG001
) -> None:
    ensure_default_llm_provider(db_session)
    user = create_test_user(db_session, email_prefix="dr_research_agent_timeout")
    chat_session = create_chat_session(db_session=db_session, user=user)

    llm = DeepResearchScriptLLM()

    request = SendMessageRequest(
        message="Compare the alpha and beta markets",
        chat_session_id=chat_session.id,
        deep_research=True,
    )

    with (
        patch("onyx.chat.prepare.get_llm_for_persona", return_value=llm),
        patch("onyx.chat.prepare.SKIP_DEEP_RESEARCH_CLARIFICATION", True),
        patch(
            "onyx.deep_research.agent.RESEARCH_AGENT_TIMEOUT_SECONDS",
            TEST_TIMEOUT_SECONDS,
        ),
    ):
        parts: list[AnswerStreamPart] = list(
            handle_stream_message_objects(new_msg_req=request, user=user)
        )

    errors = [part for part in parts if isinstance(part, StreamingError)]
    assert not errors, errors

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
    saved_research_calls = [
        tool_call
        for tool_call in assistant_message.tool_calls or []
        if tool_call.tool_id == research_agent_tool_id
    ]
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
