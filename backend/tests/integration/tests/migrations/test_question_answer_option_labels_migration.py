"""ce6d912380d7 rewrites the saved answers that name one `option_label` to
`option_labels`: in question request rows, in the results of question tool
calls, and in the checkpoints of parked responses. The rows then load."""

import json
from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from onyx.chat.models import SavedToolQuestion
from onyx.configs.app_configs import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.configs.constants import MessageType
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from onyx.db.enums import QuestionAnsweredVia, QuestionOutcome
from onyx.db.models import (
    ChatMessage,
    ChatResponseCheckpoint,
    ChatSession,
    QuestionRequest,
    ToolCall,
)
from onyx.tools.tool_implementations.question.models import QuestionToolDetails
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "c14c2689b392"

QUESTION = {
    "id": "scope",
    "header": "Scope",
    "question": "Who should get the email?",
    "options": [
        {"label": "Team", "description": "Only the team."},
        {"label": "Company", "description": "Everyone."},
    ],
}
OLD_ANSWERS = [
    {"question_id": "scope", "option_label": "Company", "user_note": "EU"},
    {"question_id": "other", "option_label": None, "user_note": "Later"},
]
NEW_ANSWERS = [
    {"question_id": "scope", "option_labels": ["Company"], "user_note": "EU"},
    {"question_id": "other", "option_labels": [], "user_note": "Later"},
]
# A tool's arguments in a parked response that use the answers' and the
# questions' key names; only question results and question rows change.
UNRELATED_ARGUMENTS = {
    "question_id": "q1",
    "option_label": "kept",
    "question": "Kept?",
    "options": [],
    "multi_select": True,
}


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
    downgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
    )
    engine = create_engine(
        build_connection_string(
            db=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            db_api=SYNC_DB_API,
        )
    )
    try:
        yield engine
    finally:
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
        engine.dispose()


def test_saved_answers_name_their_options_in_a_list(engine: Engine) -> None:
    question_request_id = uuid4()
    with Session(engine) as session:
        chat = ChatSession()
        session.add(chat)
        session.flush()
        message = ChatMessage(
            chat_session_id=chat.id,
            message="",
            token_count=0,
            message_type=MessageType.ASSISTANT,
        )
        session.add(message)
        session.flush()
        call = ToolCall(
            chat_session_id=chat.id,
            parent_chat_message_id=message.id,
            turn_number=0,
            tool_call_id="call_ask",
            tool_call_arguments={"questions": [QUESTION]},
            tool_call_tokens=0,
        )
        session.add(call)
        session.flush()
        chat_id, message_id, call_id = chat.id, message.id, call.id
        session.commit()
    try:
        details = {
            "type": "question",
            "outcome": QuestionOutcome.ANSWERED.value,
            "answers": OLD_ANSWERS,
        }
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO question_request (id, chat_session_id, chat_message_id, "
                    "tool_call_id, questions, answers, outcome, answered_via) VALUES "
                    "(:id, :chat, :message, 'call_ask', CAST(:questions AS jsonb), "
                    "CAST(:answers AS jsonb), :outcome, :via)"
                ),
                {
                    "id": question_request_id,
                    "chat": chat_id,
                    "message": message_id,
                    "questions": json.dumps([QUESTION]),
                    "answers": json.dumps(OLD_ANSWERS),
                    "outcome": QuestionOutcome.ANSWERED.name,
                    "via": QuestionAnsweredVia.CARD.name,
                },
            )
            conn.execute(
                text(
                    "UPDATE tool_call SET result = CAST(:result AS jsonb) WHERE id = :id"
                ),
                {
                    "id": call_id,
                    "result": json.dumps(
                        {
                            "role": "tool_result",
                            "tool_call_id": "call_ask",
                            "tool_name": "request_user_input",
                            "content": "",
                            "details": details,
                        }
                    ),
                },
            )
            conn.execute(
                text(
                    "INSERT INTO chat_response_checkpoint (chat_message_id, state) "
                    "VALUES (:message, CAST(:state AS jsonb))"
                ),
                {
                    "message": message_id,
                    "state": json.dumps(
                        {
                            "answers": {"request": {"result": {"details": details}}},
                            "arguments": UNRELATED_ARGUMENTS,
                        }
                    ),
                },
            )

        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
        with Session(engine) as session:
            question = session.get(QuestionRequest, question_request_id)
            assert question is not None
            saved = SavedToolQuestion.model_validate(question)
            assert [
                answer.model_dump() for answer in saved.answers or []
            ] == NEW_ANSWERS
            call = session.get(ToolCall, call_id)
            assert call is not None and call.result is not None
            assert isinstance(call.result.details, QuestionToolDetails)
            assert [
                answer.model_dump() for answer in call.result.details.answers or []
            ] == NEW_ANSWERS
            checkpoint = session.get(ChatResponseCheckpoint, message_id)
            assert checkpoint is not None
            assert checkpoint.state == {
                "answers": {
                    "request": {
                        "result": {"details": {**details, "answers": NEW_ANSWERS}}
                    }
                },
                "arguments": UNRELATED_ARGUMENTS,
            }

        # The downgrade keeps the first option of each answer, and drops
        # `multi_select`.
        chosen = [
            {"question_id": "scope", "option_labels": ["Company", "Team"]},
            {"question_id": "other", "option_labels": [], "user_note": "Later"},
        ]
        first = [
            {"question_id": "scope", "option_label": "Company"},
            {"question_id": "other", "option_label": None, "user_note": "Later"},
        ]
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE question_request SET questions = CAST(:questions AS jsonb), "
                    "answers = CAST(:answers AS jsonb) WHERE id = :id"
                ),
                {
                    "id": question_request_id,
                    "questions": json.dumps([{**QUESTION, "multi_select": True}]),
                    "answers": json.dumps(chosen),
                },
            )
            conn.execute(
                text(
                    "UPDATE tool_call SET result = jsonb_set(result, "
                    "'{details,answers}', CAST(:answers AS jsonb)) WHERE id = :id"
                ),
                {"id": call_id, "answers": json.dumps(chosen)},
            )
            conn.execute(
                text(
                    "UPDATE chat_response_checkpoint SET state = jsonb_set(state, "
                    "'{answers,request,result,details,answers}', "
                    "CAST(:answers AS jsonb)) WHERE chat_message_id = :message"
                ),
                {"message": message_id, "answers": json.dumps(chosen)},
            )
        downgrade_postgres(
            database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
        )
        with engine.connect() as conn:
            assert conn.execute(
                text(
                    "SELECT questions, answers, "
                    "(SELECT result -> 'details' -> 'answers' FROM tool_call "
                    "WHERE id = :call), "
                    "(SELECT state #> '{answers,request,result,details,answers}' "
                    "FROM chat_response_checkpoint WHERE chat_message_id = :message) "
                    "FROM question_request WHERE id = :id"
                ),
                {"id": question_request_id, "call": call_id, "message": message_id},
            ).one() == ([QUESTION], first, first, first)
            assert (
                conn.execute(
                    text(
                        "SELECT state -> 'arguments' FROM chat_response_checkpoint "
                        "WHERE chat_message_id = :message"
                    ),
                    {"message": message_id},
                ).scalar_one()
                == UNRELATED_ARGUMENTS
            )
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM chat_session WHERE id = :id"), {"id": chat_id}
            )
