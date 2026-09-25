import json
import threading
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.chat.models import AnswerStreamPart, StreamingError
from onyx.chat.process_message import handle_stream_message_objects
from onyx.configs.chat_configs import LLM_SOCKET_READ_TIMEOUT
from onyx.db.chat import get_chat_messages_by_session
from onyx.db.tools import get_tool_by_name
from onyx.deep_research.dr_mock_tools import (
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TASK_KEY,
    RESEARCH_AGENT_TOOL_NAME,
)
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.llm.interfaces import (
    LLM,
    LanguageModelInput,
    LLMConfig,
    LLMUserIdentity,
    ReasoningEffort,
    ToolChoice,
)
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    FunctionCall,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.llm.models import ChatCompletionMessage, ToolMessage
from onyx.server.query_and_chat.models import MessageResponseIDInfo, SendMessageRequest
from onyx.tools.fake_tools import research_agent
from onyx.tools.fake_tools.research_agent import RESEARCH_AGENT_TIMEOUT_MESSAGE
from onyx.tools.models import ToolCallKickoff
from tests.external_dependency_unit.answer.conftest import ensure_default_llm_provider
from tests.external_dependency_unit.answer.stream_test_utils import (
    create_chat_session,
)
from tests.external_dependency_unit.conftest import create_test_user

FAST_TASK = "Research the alpha market"
SLOW_TASK = "Research the beta market"
FAST_CALL_ID = "call_research_fast"
SLOW_CALL_ID = "call_research_slow"
RESEARCH_PLAN = "1. Research alpha\n2. Research beta"
FAST_REPORT = "Alpha market findings."
FINAL_REPORT = "Final report on alpha."
TEST_TIMEOUT_SECONDS = 5
SLOW_CHILD_MAX_BLOCK_SECONDS = 120


class ScriptedToolCall(BaseModel):
    call_id: str
    name: str
    arguments: dict[str, str] = {}


class RecordedRequest:
    def __init__(
        self, messages: list[ChatCompletionMessage], tools: list[dict]
    ) -> None:
        self.messages = messages
        self.tool_names = {tool["function"]["name"] for tool in tools}

    def tool_responses(self) -> dict[str, str]:
        return {
            message.tool_call_id: message.content
            for message in self.messages
            if isinstance(message, ToolMessage)
        }

    def mentions(self, text: str) -> bool:
        return any(
            isinstance(message.content, str) and text in message.content
            for message in self.messages
        )


class DeepResearchScriptLLM(LLM):
    """Answers each Deep Research step by the shape of its request.

    Safe to call from the parallel research-agent threads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: list[RecordedRequest] = []

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="mock",
            model_name="mock",
            temperature=1.0,
            max_input_tokens=1_000_000_000,
        )

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,  # noqa: ARG002
        structured_response_format: dict | None = None,  # noqa: ARG002
        max_tokens: int | None = None,  # noqa: ARG002
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,  # noqa: ARG002
        user_identity: LLMUserIdentity | None = None,  # noqa: ARG002
        stall_timeout_s: int = LLM_SOCKET_READ_TIMEOUT,  # noqa: ARG002
    ) -> Iterator[ModelResponseStream]:
        request = RecordedRequest(
            messages=list(prompt) if isinstance(prompt, list) else [prompt],
            tools=tools or [],
        )
        with self._lock:
            self.requests.append(request)

        reply = self._reply(request)
        if isinstance(reply, str):
            yield _chunk(Delta(content=reply))
            return
        yield _chunk(
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id=call.call_id,
                        index=index,
                        function=FunctionCall(
                            name=call.name, arguments=json.dumps(call.arguments)
                        ),
                    )
                    for index, call in enumerate(reply)
                ]
            )
        )

    @staticmethod
    def _reply(request: RecordedRequest) -> str | list[ScriptedToolCall]:
        if RESEARCH_AGENT_TOOL_NAME in request.tool_names:
            if request.tool_responses():
                return [
                    ScriptedToolCall(
                        call_id="call_orchestrator_report",
                        name=GENERATE_REPORT_TOOL_NAME,
                    )
                ]
            return [
                ScriptedToolCall(
                    call_id=FAST_CALL_ID,
                    name=RESEARCH_AGENT_TOOL_NAME,
                    arguments={RESEARCH_AGENT_TASK_KEY: FAST_TASK},
                ),
                ScriptedToolCall(
                    call_id=SLOW_CALL_ID,
                    name=RESEARCH_AGENT_TOOL_NAME,
                    arguments={RESEARCH_AGENT_TASK_KEY: SLOW_TASK},
                ),
            ]
        if GENERATE_REPORT_TOOL_NAME in request.tool_names:
            return [
                ScriptedToolCall(
                    call_id="call_child_report", name=GENERATE_REPORT_TOOL_NAME
                )
            ]
        if request.tool_responses():
            return FINAL_REPORT
        if request.mentions(FAST_TASK):
            return FAST_REPORT
        return RESEARCH_PLAN


def _chunk(delta: Delta) -> ModelResponseStream:
    return ModelResponseStream(
        id="chatcmpl-deep-research",
        created="1",
        choice=StreamingChoice(index=0, delta=delta),
    )


@pytest.fixture
def release_slow_child() -> Iterator[threading.Event]:
    release = threading.Event()
    try:
        yield release
    finally:
        release.set()


def test_timed_out_research_agent_is_a_failed_call(
    db_session: Session,
    full_deployment_setup: None,  # noqa: ARG001
    mock_external_deps: None,  # noqa: ARG001
    release_slow_child: threading.Event,
) -> None:
    ensure_default_llm_provider(db_session)
    user = create_test_user(db_session, email_prefix="dr_research_agent_timeout")
    chat_session = create_chat_session(db_session=db_session, user=user)

    llm = DeepResearchScriptLLM()
    real_research_agent_call = research_agent.run_research_agent_call

    def _research_agent_call(
        research_agent_call: ToolCallKickoff, *args: Any
    ) -> ResearchAgentCallResult | None:
        if research_agent_call.tool_args[RESEARCH_AGENT_TASK_KEY] == SLOW_TASK:
            release_slow_child.wait(timeout=SLOW_CHILD_MAX_BLOCK_SECONDS)
            return None
        return real_research_agent_call(research_agent_call, *args)

    request = SendMessageRequest(
        message="Compare the alpha and beta markets",
        chat_session_id=chat_session.id,
        deep_research=True,
    )

    with (
        patch("onyx.chat.process_message.get_llm_for_persona", return_value=llm),
        patch("onyx.deep_research.dr_loop.SKIP_DEEP_RESEARCH_CLARIFICATION", True),
        patch.object(
            research_agent, "RESEARCH_AGENT_TIMEOUT_SECONDS", TEST_TIMEOUT_SECONDS
        ),
        patch.object(research_agent, "run_research_agent_call", _research_agent_call),
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
        SLOW_CALL_ID: RESEARCH_AGENT_TIMEOUT_MESSAGE,
    }

    # Only the successful child is saved as a research agent tool call.
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
    ] == [(FAST_CALL_ID, FAST_REPORT)]
