"""Usage, setup and weekly history reads against a migrated local PostgreSQL.

Each test copies the source tables into a new schema and reads it as a tenant.
"""

import json
import uuid
from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.fleet_telemetry import (
    UsageWeek,
    limit_statement_time,
    message_id_at,
    setup_counts,
    usage_counts,
    usage_week_rows,
)
from onyx.db.models import ChatMessage
from onyx.utils import fleet_telemetry_collector as collector
from tests.unit.fakes import FakeCache
from tests.utils.fleet_telemetry import make_sender

_TABLES: tuple[str, ...] = (
    "user",
    "persona",
    "chat_session",
    "chat_message",
    "user_file",
    "build_session",
    "llm_provider",
    "mcp_server",
    "tool",
    "document_set",
    "slack_bot",
    "sso_provider",
)
_U1, _U2, _U3, _BOT = (uuid.uuid4() for _ in range(4))
_S1, _S2, _S3, _S4, _S5 = (uuid.uuid4() for _ in range(5))
_NOW: datetime = datetime.now(timezone.utc)
# Weeks of old history: A has questions, B has none, C has questions.
_WEEK_A: date = date(2026, 1, 5)
_WEEK_B: date = date(2026, 1, 12)
_WEEK_C: date = date(2026, 1, 19)
_WEEK_D: date = date(2026, 1, 26)


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)


# (session, message type, sent at), in send order, so IDs grow with time.
# S3 belongs to a bot account; S4 is an agent sub-session of S1.
_MESSAGES: list[tuple[uuid.UUID, str, datetime]] = [
    (_S1, "USER", _at(_WEEK_A, 9)),
    (_S1, "ASSISTANT", _at(_WEEK_A, 9, 1)),
    (_S1, "USER", _at(_WEEK_A + timedelta(days=2), 10)),
    (_S3, "USER", _at(_WEEK_A + timedelta(days=3), 10)),
    (_S4, "USER", _at(_WEEK_A + timedelta(days=3), 11)),
    (_S2, "USER", _at(_WEEK_C, 0, 30)),
    (_S5, "USER", _at(_WEEK_C + timedelta(days=6), 23, 59)),
    (_S1, "USER", _NOW - timedelta(days=40)),
    (_S2, "USER", _NOW - timedelta(days=10)),
    (_S2, "USER", _NOW - timedelta(days=3)),
    (_S2, "USER", _NOW - timedelta(days=3)),
    (_S2, "ASSISTANT", _NOW - timedelta(days=3)),
    (_S1, "USER", _NOW - timedelta(days=3)),
    (_S3, "USER", _NOW - timedelta(days=3)),
    (_S4, "USER", _NOW - timedelta(days=3)),
    (_S1, "USER", _NOW - timedelta(hours=2)),
    (_S5, "USER", _NOW - timedelta(hours=2)),
]


def _rows() -> str:
    users: str = ",\n".join(
        f"('{user}', 'private.{index}@poc.example.com', 'x', true, false, true, '{kind}')"
        for index, (user, kind) in enumerate(
            ((_U1, "STANDARD"), (_U2, "STANDARD"), (_U3, "STANDARD"), (_BOT, "BOT"))
        )
    )
    messages: str = ",\n".join(
        f"('{session}', 'PRIVATE question', 1, '{kind}', '{sent.isoformat()}')"
        for session, kind, sent in _MESSAGES
    )
    return f"""
INSERT INTO "user" (id, email, hashed_password, is_active, is_superuser, is_verified,
  account_type)
VALUES {users};
INSERT INTO persona (id, name, description, deleted, is_listed, is_public, builtin_persona)
VALUES
  (0, 'PRIVATE default', '', false, true, true, true),
  (5, 'PRIVATE sales agent', '', false, true, true, false),
  (6, 'PRIVATE deleted agent', '', true, true, true, false),
  (7, 'PRIVATE other builtin', '', false, true, true, true);
INSERT INTO chat_session (id, user_id, persona_id, deleted, shared_status, onyxbot_flow)
VALUES
  ('{_S1}', '{_U1}', 0, false, 'PRIVATE', false),
  ('{_S2}', '{_U2}', 5, false, 'PRIVATE', false),
  ('{_S3}', '{_BOT}', 0, false, 'PRIVATE', false),
  ('{_S4}', '{_U1}', 5, false, 'PRIVATE', false),
  ('{_S5}', '{_U3}', NULL, false, 'PRIVATE', false);
INSERT INTO chat_message (chat_session_id, message, token_count, message_type, time_sent)
VALUES {messages};
UPDATE chat_session SET spawned_by_message_id = (SELECT min(id) FROM chat_message)
WHERE id = '{_S4}';
INSERT INTO user_file (id, user_id, file_id, name, file_type, status, created_at)
VALUES
  ('{uuid.uuid4()}', '{_U1}', 'f1', 'PRIVATE.pdf', 'pdf', 'FAILED', now() - interval '1 day'),
  ('{uuid.uuid4()}', '{_U1}', 'f2', 'PRIVATE.pdf', 'pdf', 'COMPLETED', now() - interval '1 day'),
  ('{uuid.uuid4()}', '{_U2}', 'f3', 'PRIVATE.pdf', 'pdf', 'FAILED', now() - interval '10 days');
INSERT INTO build_session (id, user_id, created_at)
VALUES
  ('{uuid.uuid4()}', '{_U1}', now() - interval '1 day'),
  ('{uuid.uuid4()}', '{_U2}', now() - interval '20 days');
INSERT INTO llm_provider (name, provider)
VALUES ('PRIVATE a', 'openai'), ('PRIVATE b', 'openai'), ('PRIVATE gateway', 'PRIVATE-gw');
INSERT INTO mcp_server (owner, name, server_url)
VALUES ('PRIVATE', 'PRIVATE mcp', 'https://PRIVATE.example.com');
INSERT INTO tool (name, enabled, openapi_schema)
VALUES ('PRIVATE action', true, '{{}}'), ('PRIVATE builtin', true, NULL);
INSERT INTO document_set (name, is_up_to_date, is_public) VALUES ('PRIVATE set', true, true);
INSERT INTO sso_provider (name, display_name, provider_type, config, enabled)
VALUES
  ('private-a', 'PRIVATE', 'OIDC', '\\x00', true),
  ('private-b', 'PRIVATE', 'SAML', '\\x00', false);
"""


@pytest.fixture
def schema(db_session: Session) -> Generator[str, None, None]:
    name: str = "telemetry_usage_" + uuid.uuid4().hex[:12]
    db_session.execute(text(f'CREATE SCHEMA "{name}"'))
    for table in _TABLES:
        db_session.execute(
            text(
                f'CREATE TABLE "{name}"."{table}" (LIKE public."{table}" INCLUDING ALL)'
            )
        )
    db_session.execute(text(f'SET LOCAL search_path TO "{name}"'))
    db_session.execute(text(_rows()))
    db_session.commit()
    try:
        yield name
    finally:
        db_session.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        db_session.commit()


def test_weekly_history_counts_questions_sessions_and_people(schema: str) -> None:
    with get_session_with_tenant(tenant_id=schema) as db_session:
        limit_statement_time(db_session)
        rows: list[UsageWeek] = usage_week_rows(db_session, _WEEK_A, _WEEK_D)
        assert rows == [
            # The assistant answer, the bot's question and the sub-session are left out
            # of questions and people; the bot's session still counts.
            UsageWeek(_WEEK_A, queries=3, sessions=2, active_users=1),
            UsageWeek(_WEEK_C, queries=2, sessions=2, active_users=2),
        ]
        # A Sunday 23:59 question stays in its own week.
        assert usage_week_rows(db_session, _WEEK_D, _WEEK_D + timedelta(weeks=1)) == []
        assert usage_week_rows(db_session, _WEEK_B, _WEEK_C) == []


def test_message_id_bound_skips_older_messages(schema: str) -> None:
    with get_session_with_tenant(tenant_id=schema) as db_session:
        ids: list[int] = list(
            db_session.scalars(select(ChatMessage.id).order_by(ChatMessage.id))
        )
        # The bound reaches back one hour: the first week-C message is the first
        # message sent at or after 23:30 the day before.
        assert message_id_at(db_session, _at(_WEEK_C, 0, 30)) == ids[5]
        assert message_id_at(db_session, _at(_WEEK_C, 1, 31)) == ids[6]
        assert message_id_at(db_session, _NOW + timedelta(days=1)) == ids[-1] + 1
        assert message_id_at(db_session, _at(date(2020, 1, 6), 0)) == ids[0]


def test_usage_and_setup_are_counts_only(schema: str) -> None:
    with get_session_with_tenant(tenant_id=schema) as db_session:
        limit_statement_time(db_session)
        usage: dict[str, Any] = usage_counts(db_session, _NOW)
        setup = setup_counts(db_session)
    assert usage == {
        "active_users_1d": 2,
        "active_users_7d": 3,
        "active_users_30d": 3,
        "queries_7d": 6,
        "queries_30d": 7,
        "users_by_queries_7d": {
            "q1": 1,
            "q2_5": 2,
            "q6_20": 0,
            "q21_50": 0,
            "q51_plus": 0,
        },
        # A session with no agent goes to the default agent.
        "agent_messages_7d": {"builtin": 4, "custom": 2},
        "agents_used_7d": 2,
        "uploads_7d": 2,
        "failed_uploads_7d": 1,
        "craft_sessions_7d": 1,
        "craft_sessions_total": 2,
    }
    assert collector.setup_data(*setup) == {
        "agents": 1,
        "mcp_servers": 1,
        "custom_actions": 1,
        "document_sets": 1,
        "slack_bots": 0,
        "sso_providers": 1,
        "llm_providers": {"openai": 2, "custom": 1},
        "sso_configured": True,
    }


def _due_now(cache: FakeCache, next_week: str | None = None) -> None:
    past: float = _NOW.timestamp() - 1
    cache.set(collector._USAGE_DUE_KEY, str(past))
    cache.set(
        collector._HISTORY_KEY,
        json.dumps({"next_week": next_week, "cycle_started_at": past, "due_at": past}),
    )


def test_a_pass_sends_usage_setup_and_the_first_weeks(
    schema: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sender = make_sender(capacity=256)
    cache = FakeCache()
    monkeypatch.setattr(collector, "_jitter", lambda _low, high: high)
    _due_now(cache)
    collector.collect_usage(sender, cache, schema, _NOW)
    events: list[dict[str, Any]] = sender._take_batch()
    assert sender.invalid == 0 and "usage_errors" not in sender.health
    assert [event["event_type"] for event in events] == [
        "usage",
        "setup",
        *["usage_week"] * collector._HISTORY_WEEKS_PER_READ,
    ]
    assert [
        (event["data"]["week_start"], event["data"]["queries"]) for event in events[2:]
    ] == [
        (_WEEK_A.isoformat(), 3),
        (_WEEK_B.isoformat(), 0),
        (_WEEK_C.isoformat(), 2),
        (_WEEK_D.isoformat(), 0),
    ]
    assert "PRIVATE" not in json.dumps(events)
    # Nothing is due right after a read.
    collector.collect_usage(sender, cache, schema, _NOW + timedelta(minutes=5))
    assert sender._take_batch() == []
    # The next read resumes after the weeks already sent.
    later: datetime = _NOW + timedelta(seconds=collector._HISTORY_GAP_SECONDS[1] + 1)
    collector.collect_usage(sender, cache, schema, later)
    assert [event["data"]["week_start"] for event in sender._take_batch()] == [
        (_WEEK_D + timedelta(weeks=week)).isoformat()
        for week in range(1, collector._HISTORY_WEEKS_PER_READ + 1)
    ]


def test_a_slow_usage_read_does_not_stop_the_other_reads(
    schema: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow(db_session: Session, _now: datetime) -> dict[str, Any]:
        db_session.execute(text("SELECT pg_sleep(3)"))
        return {}

    monkeypatch.setattr(collector, "usage_counts", slow)
    sender = make_sender(capacity=256)
    cache = FakeCache()
    _due_now(cache, next_week=_WEEK_C.isoformat())
    collector.collect_usage(sender, cache, schema, _NOW)
    events: list[dict[str, Any]] = sender._take_batch()
    assert sender.health["usage_errors"] == 1
    assert events[0]["event_type"] == "setup"
    assert events[1]["data"] == {
        "week_start": _WEEK_C.isoformat(),
        "queries": 2,
        "sessions": 2,
        "active_users": 2,
    }
