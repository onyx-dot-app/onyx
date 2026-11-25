"""convert saved question answers to option_labels

Revision ID: ce6d912380d7
Revises: c14c2689b392
Create Date: 2026-11-24 17:05:50.262194

A question answer names its chosen options in `option_labels`, a list, where
it named one option in `option_label`. The answers are saved in three places:
the question request rows, the results of question tool calls, and the
checkpoints of parked responses, whose runs hold the answers they received.
This revision rewrites each answer, `{"question_id", "option_label": X}`, to
`{"question_id", "option_labels": [X]}`; an answer without an option gets an
empty list. It changes only the answers of the request rows and of question
results (`QuestionToolDetails`: "type": "question" with an outcome), and
only answers that name their question, not other JSON with the same keys. The downgrade
keeps the first option, and removes `multi_select` from the request rows'
questions, which the earlier code does not accept.

Limits, accepted because no release has the question tool:
- A response that waits when the upgrade runs, and whose saved steps or
  earlier history hold an answered question, cannot resume: its checkpoint
  digests hash the answers as they were.
- After a downgrade, a question that a Claude model asked after the upgrade
  keeps its question text as its ID and can have a fourth option, which the
  earlier code does not load.
- An old API pod that answers a waiting question after this revision reads
  its rows saves `option_label`, which the new code does not load.
"""

import json
from collections.abc import Callable

import sqlalchemy as sa
from alembic import op
from pydantic import JsonValue


# revision identifiers, used by Alembic.
revision = "ce6d912380d7"
down_revision = "c14c2689b392"
branch_labels = None
depends_on = None

# Only an answered question request has answers, and only its call's result
# and its response's checkpoint hold them, so the filters select those rows
# by the request rows.
_ANSWERED = "FROM question_request WHERE answers IS NOT NULL"
# The JSON columns whose question results (`QuestionToolDetails`, with
# "type": "question") hold answers: table, row key, column and filter.
_RESULT_COLUMNS = (
    (
        "tool_call",
        "id",
        "result",
        "(parent_chat_message_id, tool_call_id) IN "
        f"(SELECT chat_message_id, tool_call_id {_ANSWERED})",
    ),
    (
        "chat_response_checkpoint",
        "chat_message_id",
        "state",
        f"chat_message_id IN (SELECT chat_message_id {_ANSWERED})",
    ),
)

Change = Callable[[dict[str, JsonValue]], dict[str, JsonValue]]


def _to_option_labels(answer: dict[str, JsonValue]) -> dict[str, JsonValue]:
    if "option_label" in answer:
        label = answer.pop("option_label")
        answer["option_labels"] = [label] if label else []
    return answer


def _to_option_label(answer: dict[str, JsonValue]) -> dict[str, JsonValue]:
    if "option_labels" in answer:
        labels = answer.pop("option_labels")
        answer["option_label"] = (
            labels[0] if isinstance(labels, list) and labels else None
        )
    return answer


def _each(value: JsonValue, change: Change, key: str) -> JsonValue:
    """`change` applied to each object of a list that has `key`."""
    if not isinstance(value, list):
        return value
    return [
        change(dict(item)) if isinstance(item, dict) and key in item else item
        for item in value
    ]


def _in_question_results(value: JsonValue, change: Change) -> JsonValue:
    """`change` applied to each answer of the question results in `value`."""
    if isinstance(value, list):
        return [_in_question_results(item, change) for item in value]
    if not isinstance(value, dict):
        return value
    rewritten = {key: _in_question_results(item, change) for key, item in value.items()}
    # A QuestionToolDetails: its type, outcome and answers.
    if (
        rewritten.get("type") == "question"
        and "outcome" in rewritten
        and "answers" in rewritten
    ):
        rewritten["answers"] = _each(rewritten["answers"], change, "question_id")
    return rewritten


def _rewrite(
    table: str,
    key: str,
    column: str,
    where: str,
    rewrite: Callable[[JsonValue], JsonValue],
) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(f"SELECT {key}, {column} FROM {table} WHERE {where}")
    ).all()
    for row_key, value in rows:
        rewritten = rewrite(value)
        if rewritten == value:
            continue
        bind.execute(
            sa.text(
                f"UPDATE {table} SET {column} = CAST(:value AS jsonb) "
                f"WHERE {key} = :key"
            ),
            {"value": json.dumps(rewritten), "key": row_key},
        )


def _rewrite_answers(change: Change) -> None:
    _rewrite(
        "question_request",
        "id",
        "answers",
        "answers IS NOT NULL",
        lambda answers: _each(answers, change, "question_id"),
    )
    for table, key, column, where in _RESULT_COLUMNS:
        _rewrite(
            table, key, column, where, lambda value: _in_question_results(value, change)
        )


def upgrade() -> None:
    _rewrite_answers(_to_option_labels)


def downgrade() -> None:
    _rewrite_answers(_to_option_label)
    _rewrite(
        "question_request",
        "id",
        "questions",
        "TRUE",
        lambda questions: _each(
            questions,
            lambda question: {
                key: item for key, item in question.items() if key != "multi_select"
            },
            "question",
        ),
    )
