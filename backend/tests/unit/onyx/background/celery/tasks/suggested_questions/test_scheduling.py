import sys
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.background.celery.tasks.suggested_questions import scheduling
from onyx.cache.interface import CacheLockAcquisitionError
from onyx.configs.constants import DocumentSource, OnyxCeleryPriority
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
    "pool, new_docs, candidates, usable, run, reason",
    [
        (None, 0, 4, 0, False, "too few documents without a question"),
        (None, 0, 5, 0, True, "first run"),
        (_pool(0, []), 0, 5, 0, True, "first run"),
        (
            _pool(5, [300, 240, 180, 120, 60]),
            0,
            50,
            5,
            False,
            "daily run limit reached",
        ),
        (_pool(5, [5]), 0, 50, 5, False, "running low, but too soon"),
        (_pool(5, [15]), 0, 50, 5, True, "running low"),
        (_pool(20, [30]), 25, 50, 20, False, "new material, but too soon"),
        (_pool(20, [90]), 25, 50, 20, True, "new material"),
        (_pool(40, [90]), 25, 50, 40, False, "enough questions and no new material"),
        (_pool(20, [90]), 19, 50, 20, False, "enough questions and no new material"),
    ],
)
def test_worth_running(
    pool: QuestionPool | None,
    new_docs: int,
    candidates: int,
    usable: int,
    run: bool,
    reason: str,
) -> None:
    decision = scheduling.worth_running(pool, NOW, new_docs, candidates, usable)

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
    pool = QuestionPool(
        questions=[
            _question("live"),
            _question("deleted"),
            _question("old", age=timedelta(days=8)),
        ]
    )

    assert scheduling.count_usable_questions(pool, {"live", "old"}, NOW) == 1


class _FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    def set_if_absent(self, key: str, value: Any, ex: int | None = None) -> bool:  # noqa: ARG002
        if key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key: str) -> bytes | None:
        value = self.values.get(key)
        return None if value is None else str(value).encode()

    def set(self, key: str, value: Any, ex: int | None = None) -> None:  # noqa: ARG002
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> _FakeCache:
    fake = _FakeCache()
    monkeypatch.setattr(scheduling, "is_enabled", lambda: True)
    monkeypatch.setattr(scheduling, "get_cache_backend", lambda **_kw: fake)
    return fake


@pytest.fixture
def sent(
    cache: _FakeCache,  # noqa: ARG001 - turns scheduling on with a fake cache
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, dict[str, Any], int, int]]:
    """Tasks sent, with the scheduling turned on and an in-memory cache."""
    calls: list[tuple[str, dict[str, Any], int, int]] = []
    client = MagicMock()
    client.send_task.side_effect = lambda name, kwargs, priority, countdown, **_kw: (
        calls.append((name, kwargs, priority, countdown))
    )
    monkeypatch.setitem(
        sys.modules,
        "onyx.background.celery.versioned_apps.client",
        MagicMock(app=client),
    )
    return calls


def test_pool_refresh_queues_once_unless_more_urgent(sent: list[Any]) -> None:
    scheduling.request_pool_refresh("tenant", RefreshReason.GROWTH)
    scheduling.request_pool_refresh("tenant", RefreshReason.GROWTH)
    scheduling.request_pool_refresh("tenant", RefreshReason.FIRST_RUN)
    scheduling.request_pool_refresh("tenant", RefreshReason.POOL_SHORT)

    assert [
        (kwargs["reason"], priority, countdown)
        for _, kwargs, priority, countdown in sent
    ] == [
        ("growth", OnyxCeleryPriority.LOW, 600),
        ("first_run", OnyxCeleryPriority.HIGH, 0),
    ]
    assert sent[0][1]["tenant_id"] == "tenant"


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

    scheduling.request_user_topup("tenant", alice, UserRecord(), NOW)
    scheduling.request_user_topup("tenant", alice, UserRecord(), NOW)
    scheduling.request_user_topup(
        "tenant", bob, UserRecord(topups=[NOW - timedelta(minutes=2)]), NOW
    )

    assert [(kwargs["user_id"], priority) for _, kwargs, priority, _ in sent] == [
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
        scheduling, "load_settings", lambda: Settings(application_status=status)
    )

    assert scheduling.is_enabled() is enabled


@pytest.fixture
def pool_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {
        "pool": QuestionPool(questions=[_question("kept"), _question("deleted")]),
        "saved": None,
        "refreshes": [],
    }
    monkeypatch.setattr(scheduling, "is_enabled", lambda: True)
    monkeypatch.setattr(scheduling, "pool_lock", lambda _wait: nullcontext())
    monkeypatch.setattr(scheduling, "load_pool", lambda **_kw: state["pool"])
    monkeypatch.setattr(scheduling, "save_pool", lambda pool: state.update(saved=pool))
    monkeypatch.setattr(scheduling, "get_session_with_current_tenant", MagicMock())
    monkeypatch.setattr(scheduling, "get_live_document_ids", lambda _s, _ids: {"kept"})
    monkeypatch.setattr(
        scheduling,
        "request_pool_refresh",
        lambda _tenant_id, reason: state["refreshes"].append(reason),
    )
    return state


def test_drop_orphaned_questions_saves_and_asks_for_a_refill(
    pool_store: dict[str, Any],
) -> None:
    scheduling.drop_orphaned_questions("tenant")

    assert [q.document_id for q in pool_store["saved"].questions] == ["kept"]
    assert pool_store["refreshes"] == [RefreshReason.POOL_SHORT]


def test_drop_orphaned_questions_changes_nothing_when_all_live(
    pool_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        scheduling, "get_live_document_ids", lambda _s, _ids: {"kept", "deleted"}
    )

    scheduling.drop_orphaned_questions("tenant")

    assert pool_store["saved"] is None
    assert pool_store["refreshes"] == []


def test_drop_orphaned_questions_leaves_a_busy_pool(
    pool_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def busy(_wait: float) -> Any:
        raise CacheLockAcquisitionError("held by a run")

    monkeypatch.setattr(scheduling, "pool_lock", busy)

    scheduling.drop_orphaned_questions("tenant")

    assert pool_store["saved"] is None


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
