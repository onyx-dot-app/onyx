from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import KV_SUGGESTED_QUESTIONS_USER_KEY, DocumentSource
from onyx.db.enums import AccountType
from onyx.db.models import User
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.features.suggested_questions import store
from onyx.server.features.suggested_questions.models import (
    PoolQuestion,
    QuestionKind,
    QuestionPool,
    UseCase,
)
from onyx.utils.special_types import JSON_ro

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


class _FakeKvStore:
    def __init__(self) -> None:
        self.data: dict[str, JSON_ro] = {}
        self.refresh_cache_calls: list[bool] = []

    def store(self, key: str, val: JSON_ro) -> None:
        self.data[key] = val

    def load(self, key: str, refresh_cache: bool = False) -> JSON_ro:
        self.refresh_cache_calls.append(refresh_cache)
        if key not in self.data:
            raise KvKeyNotFoundError()
        return self.data[key]


@contextmanager
def _no_lock(**_kwargs: object) -> Iterator[None]:
    yield


@pytest.fixture
def kv(monkeypatch: pytest.MonkeyPatch) -> _FakeKvStore:
    fake = _FakeKvStore()
    monkeypatch.setattr(store, "get_kv_store", lambda: fake)
    monkeypatch.setattr(
        store,
        "load_user_record_values",
        lambda _session, user_ids: {
            user_id: fake.data[KV_SUGGESTED_QUESTIONS_USER_KEY.format(user_id)]
            for user_id in user_ids
            if KV_SUGGESTED_QUESTIONS_USER_KEY.format(user_id) in fake.data
        },
    )
    monkeypatch.setattr(store, "cache_shared_lock", _no_lock)
    monkeypatch.setattr(store, "get_current_tenant_id", lambda: "tenant")
    return fake


def _question(
    document_id: str, position: int = 0, age_minutes: int = 0
) -> PoolQuestion:
    return PoolQuestion(
        id=f"q_{document_id}_{position}_{age_minutes}",
        text=f"What does {document_id} say?",
        kind=QuestionKind.DOCUMENT,
        document_id=document_id,
        source_type=DocumentSource.GOOGLE_DRIVE,
        search_position=position,
        best_for=None,
        created_at=NOW - timedelta(minutes=age_minutes),
    )


def test_merge_drops_questions_whose_document_is_gone() -> None:
    merged = store.merge_questions(
        existing=[_question("kept"), _question("deleted")],
        new=[],
        live_document_ids={"kept"},
    )
    assert [question.document_id for question in merged] == ["kept"]


def test_merge_keeps_best_position_per_document_then_newest() -> None:
    old_best = _question("doc", position=0, age_minutes=60)
    new_worse = _question("doc", position=2, age_minutes=0)
    new_tied = _question("doc", position=0, age_minutes=0)

    assert store.merge_questions([old_best], [new_worse], {"doc"}) == [old_best]
    assert store.merge_questions([old_best], [new_tied], {"doc"}) == [new_tied]


def test_merge_keeps_newest_up_to_cap() -> None:
    questions = [_question(f"doc{age}", age_minutes=age) for age in range(5)]
    merged = store.merge_questions(
        existing=questions,
        new=[],
        live_document_ids={question.document_id for question in questions},
        max_size=3,
    )
    assert [question.document_id for question in merged] == ["doc0", "doc1", "doc2"]


@pytest.mark.usefixtures("kv")
def test_pool_round_trips_through_the_kv_store() -> None:
    assert store.load_pool() is None
    pool = QuestionPool(runs=[NOW], docs_at_last_run=12, questions=[_question("doc")])
    store.save_pool(pool)
    assert store.load_pool() == pool


def test_record_run_adds_the_run_and_forgets_old_ones() -> None:
    window = timedelta(hours=24)
    pool = QuestionPool(runs=[NOW - timedelta(hours=30), NOW - timedelta(hours=2)])

    updated = pool.record_run(NOW, docs_at_last_run=50, window=window)

    assert updated.runs == [NOW - timedelta(hours=2), NOW]
    assert updated.docs_at_last_run == 50
    assert updated.last_run_at() == NOW
    assert updated.runs_since(NOW - timedelta(hours=1)) == 1


@pytest.mark.usefixtures("kv")
def test_user_record_defaults_when_missing() -> None:
    record = store.load_user_record(uuid4())
    assert record.used == []
    assert record.last_seen_at is None
    assert record.topups == []


@pytest.mark.usefixtures("kv")
def test_record_seen_and_mark_used_update_one_record() -> None:
    user_id = uuid4()
    store.record_seen(user_id, NOW)
    store.mark_used(user_id, "q1")
    store.mark_used(user_id, "q1")

    record = store.load_user_record(user_id)
    assert record.last_seen_at == NOW
    assert record.used == ["q1"]


@pytest.mark.usefixtures("kv")
def test_record_seen_never_moves_the_time_back() -> None:
    user_id = uuid4()
    store.record_seen(user_id, NOW)
    store.record_seen(user_id, NOW - timedelta(minutes=1))
    assert store.load_user_record(user_id).last_seen_at == NOW


def test_locked_update_reads_postgres_not_the_cache(kv: _FakeKvStore) -> None:
    store.record_seen(uuid4(), NOW)
    assert kv.refresh_cache_calls == [True]


@pytest.mark.usefixtures("kv")
def test_mark_used_keeps_only_the_latest_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "SQ_USED_IDS_MAX", 2)
    user_id = uuid4()
    for question_id in ["q1", "q2", "q3"]:
        store.mark_used(user_id, question_id)
    assert store.load_user_record(user_id).used == ["q2", "q3"]


@pytest.mark.usefixtures("kv")
def test_record_topup_forgets_topups_outside_the_window() -> None:
    user_id = uuid4()
    window = timedelta(hours=24)
    store.record_topup(user_id, NOW - timedelta(hours=30), window)
    store.record_topup(user_id, NOW, window)
    assert store.load_user_record(user_id).topups == [NOW]


def _user(
    is_active: bool = True,
    account_type: AccountType = AccountType.STANDARD,
    personal_role: str | None = None,
) -> User:
    return User(
        id=uuid4(),
        email=f"{uuid4()}@example.com",
        is_active=is_active,
        account_type=account_type,
        personal_role=personal_role,
    )


@pytest.mark.usefixtures("kv")
def test_active_users_include_recent_and_new_but_not_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recent, stale, new = _user(), _user(), _user()
    monkeypatch.setattr(store, "get_all_users", lambda *_a, **_kw: [recent, stale, new])
    store.record_seen(recent.id, NOW - timedelta(days=1))
    store.record_seen(stale.id, NOW - timedelta(days=30))

    active = store.get_recently_active_users(MagicMock(spec=Session), now=NOW)

    assert active == [recent, new]


@pytest.mark.usefixtures("kv")
def test_active_users_leave_out_deactivated_and_non_standard_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person = _user()
    people = [
        person,
        _user(is_active=False),
        _user(account_type=AccountType.BOT),
    ]
    monkeypatch.setattr(store, "get_all_users", lambda *_a, **_kw: people)

    active = store.get_recently_active_users(MagicMock(spec=Session), now=NOW)

    assert active == [person]


def test_role_and_use_case_defaults() -> None:
    assert store.role_for(_user()) is None
    assert store.role_for(_user(personal_role="Engineer")) == "Engineer"
    assert store.use_case_for(_user()) == UseCase.OTHER
