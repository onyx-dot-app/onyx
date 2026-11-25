"""Questions that the root chat agent asks the user, through real chat turns
with a scripted model: which turns offer the question tool, which answers the
route accepts, how the query hook sees typed answers, and what a
non-streaming caller gets. Integration tests cover answering and continuing
over HTTP."""

from collections.abc import Generator
from threading import Lock
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from pydantic import JsonValue, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.chat.execution import chat_turn_work
from onyx.chat.process_message import (
    handle_multi_model_stream,
    handle_stream_message_objects,
    run_chat_turn,
)
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db.chat import delete_messages_and_files_from_chat_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import QuestionAnsweredVia, QuestionOutcome
from onyx.db.models import ChatSession, QuestionRequest, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.hooks.points.query_processing import QueryProcessingResponse
from onyx.integrations.models import ApprovalMode
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolResultMessage,
)
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat.chat_backend import (
    answer_questions,
)
from onyx.server.query_and_chat.models import (
    ChatQuestionAnswersRequest,
    QuestionAnswersResponse,
    SendMessageRequest,
)
from onyx.server.query_and_chat.streaming_models import (
    Packet,
    PacketObj,
)
from onyx.tools.constants import REQUEST_USER_INPUT_TOOL_NAME
from onyx.tools.tool_implementations.question.models import (
    MAX_QUESTIONS_BYTES,
    ToolQuestionAnswer,
)
from onyx.tools.tool_implementations.question.shapes import QUESTION_TOOL_NAMES
from tests.external_dependency_unit.chat.test_wait_agents import (
    ScriptedLLM,
)
from tests.external_dependency_unit.conftest import MakeTestUser

_NO_HEADERS = Request({"type": "http", "headers": []})
QUESTIONS: list[dict[str, JsonValue]] = [
    {
        "id": "scope",
        "header": "Scope",
        "question": "Who should get the email?",
        "options": [
            {"label": "Team (Recommended)", "description": "Only the team."},
            {"label": "Company", "description": "Everyone."},
        ],
    }
]


class Asker:
    """The model asks `rounds` times, with `calls` question calls each time,
    then answers "done" once it has their results. It records each
    request."""

    def __init__(
        self,
        calls: int = 1,
        *,
        rounds: int = 1,
        questions: list[dict[str, JsonValue]] = QUESTIONS,
    ) -> None:
        self.calls = calls
        self.rounds = rounds
        self.questions = questions
        self.requests: list[GenerationRequest] = []
        self._lock = Lock()

    def generate(
        self, request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        with self._lock:
            self.requests.append(request)
        results = sum(
            isinstance(message, ToolResultMessage) for message in request.messages
        )
        if results >= self.calls * self.rounds:
            return AssistantMessage(content=[TextContent(text="done")])
        return AssistantMessage(
            content=[
                ToolCall(
                    id=f"ask-{results}-{index}",
                    name=REQUEST_USER_INPUT_TOOL_NAME,
                    arguments={"questions": self.questions},
                )
                for index in range(self.calls)
            ]
        )

    def offered(self) -> bool:
        """Whether the first request offered the question tool."""
        return any(tool.name in QUESTION_TOOL_NAMES for tool in self.requests[0].tools)


class QuestionTurns:
    """A user's chat with the default agent and no configured tools. Reads and
    answers use their own sessions, since turns read the user on their
    threads."""

    def __init__(self, user: User, chat_session_id: UUID) -> None:
        self.user = user
        self.chat_session_id = chat_session_id

    def start(
        self,
        monkeypatch: pytest.MonkeyPatch,
        asker: Asker,
        *,
        models: list[LLMOverride] | None = None,
        approval_mode: ApprovalMode = ApprovalMode.INTERACTIVE,
    ) -> list[PacketObj]:
        """Send a message; returns the turn's packets."""
        monkeypatch.setattr("onyx.chat.execution.construct_tools", lambda **_kwargs: {})
        model = ScriptedLLM(asker.generate)
        monkeypatch.setattr(
            "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
        )
        request = SendMessageRequest(
            message="Email the team", chat_session_id=self.chat_session_id
        )
        return [
            packet.obj
            for packet in (
                handle_multi_model_stream(
                    new_msg_req=request,
                    user=self.user,
                    llm_overrides=models,
                    approval_mode=approval_mode,
                )
                if models
                else handle_stream_message_objects(
                    new_msg_req=request,
                    user=self.user,
                    approval_mode=approval_mode,
                )
            )
            if isinstance(packet, Packet)
        ]

    def rows(self) -> list[QuestionRequest]:
        with get_session_with_current_tenant() as session:
            return list(
                session.scalars(
                    select(QuestionRequest)
                    .where(QuestionRequest.chat_session_id == self.chat_session_id)
                    .order_by(QuestionRequest.tool_call_id)
                )
            )

    def answer(
        self, question_request_id: UUID, body: ChatQuestionAnswersRequest
    ) -> QuestionAnswersResponse:
        """Answer through the route, which dispatches the continuation."""
        with get_session_with_current_tenant() as session:
            return answer_questions(
                question_request_id=question_request_id,
                body=body,
                request=_NO_HEADERS,
                user=self.user,
                db_session=session,
            )


@pytest.fixture
def turns(
    db_session: Session, make_test_user: MakeTestUser
) -> Generator[QuestionTurns, None, None]:
    user = make_test_user("tool_questions")
    chat = ChatSession(
        id=uuid4(),
        user_id=user.id,
        persona_id=DEFAULT_PERSONA_ID,
        description="tool questions",
    )
    db_session.add(chat)
    db_session.commit()
    chat_id = chat.id
    try:
        yield QuestionTurns(user, chat_id)
    finally:
        try:
            assert chat_turn_work.wait_idle(timeout=30)
        finally:
            db_session.rollback()
            delete_messages_and_files_from_chat_session(chat_id, db_session)
            db_session.commit()


def _card(
    option_label: str | None, user_note: str | None = None
) -> ChatQuestionAnswersRequest:
    return ChatQuestionAnswersRequest(
        answers=[
            ToolQuestionAnswer(
                question_id="scope",
                option_labels=[option_label] if option_label else [],
                user_note=user_note,
            )
        ]
    )


@pytest.mark.parametrize("multi_model", [False, True], ids=["one_model", "two_models"])
@pytest.mark.parametrize(
    "approval_mode",
    [ApprovalMode.INTERACTIVE, ApprovalMode.NO_APPROVER],
    ids=["asks", "bot"],
)
def test_only_single_model_interactive_turns_offer_the_question_tool(
    turns: QuestionTurns,
    monkeypatch: pytest.MonkeyPatch,
    multi_model: bool,
    approval_mode: ApprovalMode,
) -> None:
    asker = Asker(calls=0)
    turns.start(
        monkeypatch,
        asker,
        models=[LLMOverride(model_version="a"), LLMOverride(model_version="b")]
        if multi_model
        else None,
        approval_mode=approval_mode,
    )
    assert asker.offered() == (
        approval_mode == ApprovalMode.INTERACTIVE and not multi_model
    )


def test_a_card_answer_must_answer_each_question_with_its_options(
    turns: QuestionTurns, monkeypatch: pytest.MonkeyPatch
) -> None:
    turns.start(monkeypatch, Asker())
    [row] = turns.rows()
    with pytest.raises(OnyxError) as missing:
        turns.answer(uuid4(), _card("Company"))
    assert missing.value.error_code == OnyxErrorCode.NOT_FOUND
    # Saving removes NUL characters, so a NUL-only text is no answer.
    with pytest.raises(ValidationError):
        ChatQuestionAnswersRequest(message="\x00 ")
    for body in (
        _card("Nobody"),
        _card(None, "  "),
        _card(None, "\x00"),
        ChatQuestionAnswersRequest(answers=[]),
    ):
        with pytest.raises(OnyxError) as invalid:
            turns.answer(row.id, body)
        assert invalid.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert turns.rows()[0].outcome is None


def test_a_complete_response_lists_the_questions_that_wait(
    turns: QuestionTurns, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-streaming caller gets the waiting questions, as it gets the
    approval requests that wait."""
    monkeypatch.setattr("onyx.chat.execution.construct_tools", lambda **_kwargs: {})
    model = ScriptedLLM(Asker().generate)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    response = run_chat_turn(
        new_msg_req=SendMessageRequest(
            message="Email the team", chat_session_id=turns.chat_session_id
        ),
        user=turns.user,
    )
    [row] = turns.rows()
    assert [
        question.question_request_id for question in response.pending_tool_questions
    ] == [str(row.id)]
    assert response.pending_tool_approvals == []


@pytest.mark.parametrize("via", ["message", "card"])
def test_the_query_hook_processes_typed_answers(
    turns: QuestionTurns, monkeypatch: pytest.MonkeyPatch, via: str
) -> None:
    """A typed message and a card's note go through the admin's query hook, as
    a chat message does: the saved answer is the hook's text."""
    turns.start(monkeypatch, Asker())
    [row] = turns.rows()
    monkeypatch.setattr(
        "onyx.chat.process_message.execute_hook",
        lambda **kwargs: QueryProcessingResponse(
            query=f"[redacted] {kwargs['payload']['query']}"
        ),
    )
    turns.answer(
        row.id,
        ChatQuestionAnswersRequest(message="Ana's phone is 555")
        if via == "message"
        else _card("Company", "Ana's phone is 555"),
    )
    [saved] = turns.rows()
    if via == "message":
        assert saved.message == "[redacted] Ana's phone is 555"
    else:
        assert saved.answers == [
            {
                "question_id": "scope",
                "option_labels": ["Company"],
                "user_note": "[redacted] Ana's phone is 555",
            }
        ]


def test_a_query_hook_that_rejects_a_typed_answer_saves_nothing(
    turns: QuestionTurns, monkeypatch: pytest.MonkeyPatch
) -> None:
    turns.start(monkeypatch, Asker())
    [row] = turns.rows()
    monkeypatch.setattr(
        "onyx.chat.process_message.execute_hook",
        lambda **_kwargs: QueryProcessingResponse(
            query=None, rejection_message="No phone numbers."
        ),
    )
    with pytest.raises(OnyxError) as rejected:
        turns.answer(row.id, ChatQuestionAnswersRequest(message="555-0100"))
    assert rejected.value.error_code == OnyxErrorCode.QUERY_REJECTED
    assert turns.rows()[0].outcome is None


@pytest.mark.parametrize(
    "field",
    [
        {"question": "x" * MAX_QUESTIONS_BYTES},
        # Saving removes NUL characters, so the saved text would differ from
        # the card's.
        {"header": "Sco\x00pe"},
    ],
    ids=["oversized", "changed_once_saved"],
)
def test_questions_that_cannot_be_saved_are_refused(
    turns: QuestionTurns,
    monkeypatch: pytest.MonkeyPatch,
    field: dict[str, JsonValue],
) -> None:
    """The model gets an error, and nothing waits."""
    [question] = QUESTIONS
    asker = Asker(questions=[{**question, **field}])
    turns.start(monkeypatch, asker)
    assert turns.rows() == []
    assert len(asker.requests) == 2


def test_the_same_typed_text_answers_a_question_asked_after_it(
    turns: QuestionTurns, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The response asks again after a typed answer. The same text answers
    the new question; a late retry for the first question returns it."""
    turns.start(monkeypatch, Asker(rounds=2))
    [first] = turns.rows()
    typed = ChatQuestionAnswersRequest(message="Yes")
    turns.answer(first.id, typed)
    assert chat_turn_work.wait_idle(timeout=30)
    _, second = turns.rows()
    assert second.outcome is None

    turns.answer(second.id, typed)
    assert chat_turn_work.wait_idle(timeout=30)
    turns.answer(first.id, typed)
    assert [(row.outcome, row.answered_via, row.message) for row in turns.rows()] == [
        (QuestionOutcome.ANSWERED, QuestionAnsweredVia.MESSAGE, "Yes")
    ] * 2
