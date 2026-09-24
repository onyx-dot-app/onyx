import threading
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.chat.models import AnswerStreamPart, StreamingError
from onyx.chat.process_message import handle_stream_message_objects
from onyx.db.chat import get_chat_messages_by_session
from onyx.db.tools import get_tool_by_name
from onyx.deep_research.dr_mock_tools import (
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TASK_KEY,
    RESEARCH_AGENT_TOOL_NAME,
)
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.llm import mock_llm_script
from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.mock_llm_script import MockLLMStep, MockToolCall
from onyx.llm.models import ToolMessage
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
FAST_REPORT = "Alpha market findings."
FINAL_REPORT = "Final report on alpha."
TEST_TIMEOUT_SECONDS = 5
SLOW_CHILD_MAX_BLOCK_SECONDS = 120

SCRIPT = [
    MockLLMStep(text="1. Research alpha\n2. Research beta"),
    MockLLMStep(
        tool_calls=[
            MockToolCall(
                id=FAST_CALL_ID,
                name=RESEARCH_AGENT_TOOL_NAME,
                arguments={RESEARCH_AGENT_TASK_KEY: FAST_TASK},
            ),
            MockToolCall(
                id=SLOW_CALL_ID,
                name=RESEARCH_AGENT_TOOL_NAME,
                arguments={RESEARCH_AGENT_TASK_KEY: SLOW_TASK},
            ),
        ]
    ),
    MockLLMStep(
        tool_calls=[MockToolCall(name=GENERATE_REPORT_TOOL_NAME)],
        match_prompt_contains=FAST_TASK,
    ),
    MockLLMStep(text=FAST_REPORT, match_prompt_contains=FAST_TASK),
    MockLLMStep(
        tool_calls=[MockToolCall(name=GENERATE_REPORT_TOOL_NAME)],
        match_prompt_contains=RESEARCH_AGENT_TIMEOUT_MESSAGE,
    ),
    MockLLMStep(text=FINAL_REPORT),
]


@pytest.fixture
def release_slow_child() -> Iterator[threading.Event]:
    release = threading.Event()
    try:
        yield release
    finally:
        release.set()


def _tool_messages(prompt: LanguageModelInput) -> dict[str, str]:
    messages = prompt if isinstance(prompt, list) else [prompt]
    return {
        message.tool_call_id: message.content
        for message in messages
        if isinstance(message, ToolMessage)
    }


def test_timed_out_research_agent_is_a_failed_call(
    db_session: Session,
    full_deployment_setup: None,  # noqa: ARG001
    mock_external_deps: None,  # noqa: ARG001
    release_slow_child: threading.Event,
) -> None:
    ensure_default_llm_provider(db_session)
    user = create_test_user(db_session, email_prefix="dr_research_agent_timeout")
    chat_session = create_chat_session(db_session=db_session, user=user)

    real_research_agent_call = research_agent.run_research_agent_call
    real_prompt_text = mock_llm_script.prompt_text_for_matching
    prompts: list[LanguageModelInput] = []

    def _research_agent_call(
        research_agent_call: ToolCallKickoff, *args: Any
    ) -> ResearchAgentCallResult | None:
        if research_agent_call.tool_args[RESEARCH_AGENT_TASK_KEY] == SLOW_TASK:
            release_slow_child.wait(timeout=SLOW_CHILD_MAX_BLOCK_SECONDS)
            return None
        return real_research_agent_call(research_agent_call, *args)

    def _record_prompt(prompt: LanguageModelInput) -> str:
        prompts.append(prompt)
        return real_prompt_text(prompt)

    request = SendMessageRequest(
        message="Compare the alpha and beta markets",
        chat_session_id=chat_session.id,
        deep_research=True,
        mock_llm_script=SCRIPT,
    )

    with (
        patch("onyx.chat.process_message.INTEGRATION_TESTS_MODE", True),
        patch("onyx.deep_research.dr_loop.SKIP_DEEP_RESEARCH_CLARIFICATION", True),
        patch.object(
            research_agent, "RESEARCH_AGENT_TIMEOUT_SECONDS", TEST_TIMEOUT_SECONDS
        ),
        patch.object(research_agent, "run_research_agent_call", _research_agent_call),
        patch("onyx.llm.multi_llm.prompt_text_for_matching", _record_prompt),
    ):
        parts: list[AnswerStreamPart] = list(
            handle_stream_message_objects(new_msg_req=request, user=user)
        )

    errors = [part for part in parts if isinstance(part, StreamingError)]
    assert not errors, errors

    # The orchestrator's next request answers the timed-out call with the failure message.
    tool_responses = [
        responses
        for responses in map(_tool_messages, prompts)
        if SLOW_CALL_ID in responses
    ]
    assert tool_responses, "No LLM request carried a response for the timed-out call"
    assert tool_responses[0] == {
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
