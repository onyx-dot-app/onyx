import sys
import types
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.configs.constants import DocumentSource, OnyxCeleryPriority
from onyx.server.features.suggested_questions import scheduling
from onyx.server.features.suggested_questions.models import (
    PoolQuestion,
    QuestionKind,
    QuestionPool,
    RefreshReason,
    UserRecord,
)
from onyx.server.settings.models import ApplicationStatus, Settings

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def _question(document_id: str, age: timedelta = timedelta(0)) -> PoolQuestion:
    return PoolQuestion(
        id=document_id,
        text=f"About {document_id}?",
        kind=QuestionKind.DOCUMENT,
        document_id=document_id,
        source_type=DocumentSource.GOOGLE_DRIVE,
        search_position=0,
        best_for=None,
        created_at=NOW - age,
    )


def _pool(questions: int = 0, runs_ago_min: list[int] | None = None) -> QuestionPool:
    return QuestionPool(
        runs=[
            NOW - timedelta(minutes=m) for m in sorted(runs_ago_min or [], reverse=True)
        ],
        questions=[_question(f"doc-{n}") for n in range(questions)],
    )


@pytest.mark.parametrize(
    "pool, candidates, run, reason",
    [
        (None, 4, False, "too few documents without a question"),
        (None, 5, True, "first run"),
        (_pool(0, []), 5, True, "first run"),
        (_pool(5, [300, 240, 180, 120, 60]), 50, False, "daily run limit reached"),
        (_pool(5, [5]), 50, False, "too soon after the last run"),
        (_pool(5, [15]), 50, True, "requested"),
        # A full shelf still runs when asked: the requester decided it is needed.
        (_pool(20, [15]), 50, True, "requested"),
    ],
)
def test_worth_running(
    pool: QuestionPool | None, candidates: int, run: bool, reason: str
) -> None:
    decision = scheduling.worth_running(pool, NOW, candidates)

    assert (decision.run, decision.reason) == (run, reason)


@pytest.mark.parametrize(
    "topups_ago_min, allowed",
    [
        ([], True),
        ([5], False),  # under the 10-minute gap
        ([60, 30], True),
        ([300, 240, 180, 120, 60], False),  # 5 in the last 24 hours
        ([1500, 240, 180, 120, 60], True),  # the oldest is outside the window
    ],
)
def test_topup_allowed(topups_ago_min: list[int], allowed: bool) -> None:
    record = UserRecord(topups=[NOW - timedelta(minutes=m) for m in topups_ago_min])

    assert scheduling.topup_allowed(record, NOW) is allowed


def test_count_usable_questions_skips_deleted_and_old() -> None:
    questions = [
        _question("live"),
        _question("deleted"),
        _question("old", age=timedelta(days=8)),
    ]

    assert scheduling.count_usable_questions(questions, {"live", "old"}, NOW) == 1


def _as_bytes(value: Any) -> bytes:
    return value if isinstance(value, bytes) else str(value).encode()


class _FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def set_if_absent(self, key: str, value: Any, ex: int | None = None) -> bool:  # noqa: ARG002
        if key in self.values:
            return False
        self.values[key] = _as_bytes(value)
        return True

    def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    def set(self, key: str, value: Any, ex: int | None = None) -> None:  # noqa: ARG002
        self.values[key] = _as_bytes(value)

    def delete(self, key: str) -> None:
        self.values.pop(key, None)

    def ttl(self, key: str) -> int:
        return 100 if key in self.values else -2

    def replace_if_value(
        self,
        key: str,
        expected: bytes,
        value: Any,
        ex: int | None = None,  # noqa: ARG002
    ) -> bool:
        if self.values.get(key) != expected:
            return False
        self.values[key] = _as_bytes(value)
        return True

    def delete_if_value(self, key: str, expected: bytes) -> bool:
        if self.values.get(key) != expected:
            return False
        del self.values[key]
        return True


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> _FakeCache:
    fake = _FakeCache()
    monkeypatch.setattr(scheduling, "is_enabled", lambda: True)
    monkeypatch.setattr(scheduling, "get_cache_backend", lambda **_kw: fake)
    # No pool yet and enough documents, so the run rules allow a first run.
    monkeypatch.setattr(scheduling, "load_pool", lambda: None)
    monkeypatch.setattr(scheduling, "get_session_with_current_tenant", MagicMock())
    monkeypatch.setattr(scheduling, "count_candidate_documents", lambda _s, _ids: 30)
    return fake


@pytest.fixture
def sent(
    cache: _FakeCache,  # noqa: ARG001 - turns scheduling on with a fake cache
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, dict[str, Any], int]]:
    """Tasks sent, with the scheduling turned on and an in-memory cache."""
    calls: list[tuple[str, dict[str, Any], int]] = []
    client = MagicMock()
    client.send_task.side_effect = lambda name, kwargs, priority, **_kw: calls.append(
        (name, kwargs, priority)
    )
    monkeypatch.setitem(
        sys.modules,
        "onyx.background.celery.versioned_apps.client",
        MagicMock(app=client),
    )
    return calls


def test_pool_refresh_queues_once_at_high_priority(sent: list[Any]) -> None:
    for _ in range(3):
        scheduling.request_pool_refresh("tenant", RefreshReason.FIRST_RUN)

    assert [(kwargs["reason"], priority) for _, kwargs, priority in sent] == [
        ("first_run", OnyxCeleryPriority.HIGH)
    ]
    assert sent[0][1]["tenant_id"] == "tenant"


@pytest.mark.parametrize(
    "pool, candidates",
    [
        (_pool(5, [5]), 30),  # too soon after the last run
        (None, 4),  # too few documents without a question
    ],
)
def test_a_request_the_run_rules_refuse_is_never_sent(
    sent: list[Any],
    cache: _FakeCache,
    monkeypatch: pytest.MonkeyPatch,
    pool: QuestionPool | None,
    candidates: int,
) -> None:
    # The pool is read through the real clock, so the last run is "now".
    if pool is not None:
        pool = pool.model_copy(update={"runs": [datetime.now(timezone.utc)]})
    monkeypatch.setattr(scheduling, "load_pool", lambda: pool)
    monkeypatch.setattr(
        scheduling, "count_candidate_documents", lambda _s, _ids: candidates
    )

    scheduling.request_pool_refresh("tenant", RefreshReason.FIRST_RUN)

    assert sent == []
    assert cache.values == {}


def test_pool_refresh_says_whether_a_run_is_queued_and_who_asked(
    sent: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = uuid4()

    first = scheduling.request_pool_refresh(
        "tenant", RefreshReason.PERSON_SHORT, requester_id=alice
    )
    already_queued = scheduling.request_pool_refresh("tenant", RefreshReason.FIRST_RUN)
    monkeypatch.setattr(scheduling, "count_candidate_documents", lambda _s, _ids: 0)
    scheduling.release_pool_flag("tenant")
    refused = scheduling.request_pool_refresh("tenant", RefreshReason.PERSON_SHORT)

    assert (first, already_queued, refused) == (True, True, False)
    assert [kwargs for _, kwargs, _ in sent] == [
        {"tenant_id": "tenant", "reason": "person_short", "requester_id": str(alice)}
    ]


def test_pool_refresh_does_nothing_when_disabled(
    sent: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scheduling, "is_enabled", lambda: False)

    scheduling.request_pool_refresh("tenant", RefreshReason.FIRST_RUN)

    assert sent == []


def test_pool_refresh_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduling, "is_enabled", MagicMock(side_effect=RuntimeError))

    scheduling.request_pool_refresh("tenant", RefreshReason.FIRST_RUN)


def test_topup_queues_once_and_respects_limits(sent: list[Any]) -> None:
    alice, bob = uuid4(), uuid4()

    queued = [
        scheduling.request_user_topup("tenant", alice, UserRecord(), NOW),
        scheduling.request_user_topup("tenant", alice, UserRecord(), NOW),
        scheduling.request_user_topup(
            "tenant", bob, UserRecord(topups=[NOW - timedelta(minutes=2)]), NOW
        ),
    ]

    assert queued == [True, True, False]  # queued, already queued, too soon

    assert [(kwargs["user_id"], priority) for _, kwargs, priority in sent] == [
        (str(alice), OnyxCeleryPriority.HIGH)
    ]


@pytest.mark.parametrize(
    "playground, status, enabled",
    [
        (True, ApplicationStatus.ACTIVE, True),
        (False, ApplicationStatus.ACTIVE, False),
        (True, ApplicationStatus.GRACE_PERIOD, False),
        (True, ApplicationStatus.GATED_ACCESS, False),
    ],
)
def test_is_enabled_only_on_an_active_playground(
    monkeypatch: pytest.MonkeyPatch,
    playground: bool,
    status: ApplicationStatus,
    enabled: bool,
) -> None:
    monkeypatch.setattr(scheduling, "IS_PLAYGROUND", playground)
    monkeypatch.setattr(
        scheduling, "load_settings", lambda **_kw: Settings(application_status=status)
    )

    assert scheduling.is_enabled() is enabled


def test_a_failed_send_removes_the_queued_flag(
    cache: _FakeCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = MagicMock()
    client.send_task.side_effect = ConnectionError("broker down")
    monkeypatch.setitem(
        sys.modules,
        "onyx.background.celery.versioned_apps.client",
        MagicMock(app=client),
    )

    scheduling.request_pool_refresh("tenant", RefreshReason.FIRST_RUN)
    scheduling.request_user_topup("tenant", uuid4(), UserRecord(), NOW)

    assert cache.values == {}
    assert client.send_task.call_count == 2


def _client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    client = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "onyx.background.celery.versioned_apps.client",
        MagicMock(app=client),
    )
    return client


_KEY = "suggested_questions_pool_queued"


def test_a_failed_send_leaves_another_requests_flag(
    cache: _FakeCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(monkeypatch)

    def another_request_wins(*_args: Any, **_kwargs: Any) -> None:
        cache.values[_KEY] = b"1:another-request"
        raise ConnectionError("broker down")

    client.send_task.side_effect = another_request_wins

    scheduling.request_pool_refresh("tenant", RefreshReason.FIRST_RUN)

    assert cache.values[_KEY] == b"1:another-request"


def test_a_failed_client_import_removes_the_flag(
    cache: _FakeCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "onyx.background.celery.versioned_apps.client",
        types.ModuleType("client_without_app"),
    )

    scheduling.request_pool_refresh("tenant", RefreshReason.FIRST_RUN)

    assert cache.values == {}


def test_a_failed_settings_read_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    monkeypatch.setattr(scheduling, "get_cache_backend", lambda **_kw: _FakeCache())
    monkeypatch.setattr(scheduling, "IS_PLAYGROUND", True)

    def unreadable(raise_on_error: bool = False) -> Settings:
        # Like load_settings: on a failed read it returns defaults (ACTIVE)
        # unless asked to raise.
        if raise_on_error:
            raise RuntimeError("settings store down")
        return Settings()

    monkeypatch.setattr(scheduling, "load_settings", unreadable)

    scheduling.request_pool_refresh("tenant", RefreshReason.FIRST_RUN)

    client.send_task.assert_not_called()


@pytest.mark.parametrize(
    "pool, requested",
    [
        (None, [RefreshReason.FIRST_RUN]),
        (QuestionPool(), [RefreshReason.FIRST_RUN]),
        # After the first run, chat opens ask for runs, not indexing.
        (_pool(3, [30]), []),
    ],
)
def test_new_documents_ask_only_for_a_first_run(
    monkeypatch: pytest.MonkeyPatch,
    pool: QuestionPool | None,
    requested: list[RefreshReason],
) -> None:
    asked: list[RefreshReason] = []
    monkeypatch.setattr(scheduling, "is_enabled", lambda: True)
    monkeypatch.setattr(scheduling, "load_pool", lambda: pool)
    monkeypatch.setattr(
        scheduling, "request_pool_refresh", lambda _t, r: asked.append(r)
    )

    scheduling.request_refresh_for_new_documents("tenant")

    assert asked == requested


def test_new_documents_never_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduling, "is_enabled", lambda: True)
    monkeypatch.setattr(scheduling, "load_pool", MagicMock(side_effect=RuntimeError))

    scheduling.request_refresh_for_new_documents("tenant")
