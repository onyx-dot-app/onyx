"""Open and answer the questions that a chat's root agent asks the user.

A call of the question tool opens a request (`open_tool_question`), and the
call waits for its result. The request row holds what the card shows: the
call's questions. A question parks its run as an approval request does
(`onyx/chat/tool_approvals.py`): the run's checkpoint is saved and its pod is
free. The user answers on the card, or by typing a message in the chat; the
answers API saves the answer, and dispatch resumes the run on any pod
(`ChatRunStore.resume`), which gives each waiting call the result of its saved
row (`question_answer`). The user's Stop of a live turn cancels the questions
that the turn's root run waits on (`ChatRunStore.reject_waiting_inputs`), and
the store cancels the questions of a run that ends when it releases the run.
"""

import json
from uuid import UUID, uuid4

from onyx.agents.tool_execution import UNAVAILABLE_CALL_MESSAGE
from onyx.agents.tools import (
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
)
from onyx.chat.models import SavedToolQuestion
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import QuestionAnsweredVia, QuestionOutcome
from onyx.db.question_request import create_question_request__no_commit
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.models import ToolResult
from onyx.tools.tool_implementations.question.models import (
    QuestionToolDetails,
    ToolQuestion,
    ToolQuestionAnswer,
)
from onyx.utils.postgres_sanitization import sanitize_string

CANCELLED_QUESTION_MESSAGE = "The user stopped the response before answering."


def open_tool_question(
    *,
    tenant_id: str,
    chat_session_id: UUID,
    response_id: int,
    tool_call_id: str,
    display_name: str,
    questions: list[ToolQuestion],
) -> PendingToolInput:
    """Save the call's questions; the call waits for their answers."""
    question_request_id = uuid4()
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        create_question_request__no_commit(
            db_session,
            question_request_id=question_request_id,
            chat_session_id=chat_session_id,
            chat_message_id=response_id,
            tool_call_id=tool_call_id,
            questions=[question.model_dump(mode="json") for question in questions],
        )
        db_session.commit()
    return PendingToolInput(
        request_id=str(question_request_id),
        prompt="\n".join(question.question for question in questions),
        mode=InputMode.RESULT,
        display_name=display_name,
    )


def card_answers(
    questions: list[ToolQuestion], answers: list[ToolQuestionAnswer]
) -> list[ToolQuestionAnswer]:
    """The card's answers in question order: each question answered once,
    with one of its options, a note, or both."""
    given = {answer.question_id: answer for answer in answers}
    if len(given) != len(answers) or set(given) != {
        question.id for question in questions
    }:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Answer each question exactly once"
        )
    ordered = [given[question.id] for question in questions]
    for question, answer in zip(questions, ordered, strict=True):
        # A note counts by the text that the answer saves.
        if not (
            answer.option_label or sanitize_string(answer.user_note or "").strip()
        ) or (
            answer.option_label is not None
            and answer.option_label not in {option.label for option in question.options}
        ):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Answer {question.id!r} with one of its options or a note",
            )
    return ordered


def question_answer(
    question_request_id: UUID, question: SavedToolQuestion | None
) -> HumanToolAnswer:
    """The result that an ended question gives the call that asked it. None
    is a question whose row was deleted with its chat or response."""
    request_id = str(question_request_id)
    if question is None:
        return HumanToolAnswer(
            request_id=request_id,
            decision=InputDecision.RESULT,
            result=ToolResult(
                content=UNAVAILABLE_CALL_MESSAGE,
                is_error=True,
                details=QuestionToolDetails(outcome=QuestionOutcome.CANCELLED),
            ),
        )
    if question.outcome is None:
        raise ValueError("A question that still waits gives no answer")
    if question.outcome == QuestionOutcome.CANCELLED:
        content = CANCELLED_QUESTION_MESSAGE
    elif question.answered_via == QuestionAnsweredVia.MESSAGE:
        # The model reads what the user typed, as the user typed it.
        content = question.message or ""
    else:
        content = json.dumps(
            {
                "answers": {
                    answer.question_id: {
                        "answers": [
                            *([answer.option_label] if answer.option_label else []),
                            *(
                                [f"user_note: {answer.user_note}"]
                                if answer.user_note
                                else []
                            ),
                        ]
                    }
                    for answer in question.answers or []
                }
            },
            ensure_ascii=False,
        )
    return HumanToolAnswer(
        request_id=request_id,
        decision=InputDecision.RESULT,
        result=ToolResult(
            content=content,
            details=QuestionToolDetails(
                outcome=question.outcome,
                answered_via=question.answered_via,
                answers=question.answers,
                message=question.message,
            ),
        ),
    )
