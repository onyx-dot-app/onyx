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
empty list. The downgrade keeps the first option, and removes `multi_select`
from the request rows' questions, which the earlier code does not accept.
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

# The JSON columns that hold answers: table, row key, column, and the filter
# that finds the rows to rewrite. Only an answered question request has
# answers, and only its call's result and its response's checkpoint hold them,
# so the filters select those rows by the request rows.
_ANSWERED = "FROM question_request WHERE answers IS NOT NULL"
_ANSWER_COLUMNS = (
    ("question_request", "id", "answers", "answers IS NOT NULL"),
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
_QUESTION_COLUMN = ("question_request", "id", "questions", "TRUE")


def _to_option_labels(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    if "question_id" in value and "option_label" in value:
        label = value.pop("option_label")
        value["option_labels"] = [label] if label else []
    return value


def _to_option_label(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    if "question_id" in value and "option_labels" in value:
        labels = value.pop("option_labels")
        value["option_label"] = (
            labels[0] if isinstance(labels, list) and labels else None
        )
    if "question" in value and "options" in value:
        value.pop("multi_select", None)
    return value


def _rewrite(
    value: JsonValue, change: Callable[[dict[str, JsonValue]], dict[str, JsonValue]]
) -> JsonValue:
    if isinstance(value, dict):
        return change({key: _rewrite(item, change) for key, item in value.items()})
    if isinstance(value, list):
        return [_rewrite(item, change) for item in value]
    return value


def _rewrite_columns(
    columns: tuple[tuple[str, str, str, str], ...],
    change: Callable[[dict[str, JsonValue]], dict[str, JsonValue]],
) -> None:
    bind = op.get_bind()
    for table, key, column, where in columns:
        rows = bind.execute(
            sa.text(f"SELECT {key}, {column} FROM {table} WHERE {where}")
        ).all()
        for row_key, value in rows:
            rewritten = _rewrite(value, change)
            if rewritten == value:
                continue
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET {column} = CAST(:value AS jsonb) "
                    f"WHERE {key} = :key"
                ),
                {"value": json.dumps(rewritten), "key": row_key},
            )


def upgrade() -> None:
    _rewrite_columns(_ANSWER_COLUMNS, _to_option_labels)


def downgrade() -> None:
    _rewrite_columns((*_ANSWER_COLUMNS, _QUESTION_COLUMN), _to_option_label)
