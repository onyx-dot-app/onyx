from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from celery.exceptions import Retry

from onyx.background.celery.tasks.suggested_questions import tasks
from onyx.cache.interface import CacheLockAcquisitionError
from onyx.configs.constants import DocumentSource
from onyx.db.models import User
from onyx.server.features.suggested_questions.models import (
    CandidateDocument,
    PoolQuestion,
    QuestionKind,
    QuestionPool,
    RunDecision,
    UserRecord,
)


def _question(document_id: str) -> PoolQuestion:
    return PoolQuestion(
        id=document_id,
        text=f"About {document_id}?",
        kind=QuestionKind.DOCUMENT,
        document_id=document_id,
        source_type=DocumentSource.GOOGLE_DRIVE,
        search_position=0,
        best_for=None,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Every step of a run mocked; the pipeline returns one new question."""
    state: dict[str, Any] = {
        "pool": QuestionPool(questions=[_question("old")]),
        "saved": None,
        "decision": RunDecision(run=True, reason="running low"),
        "released": [],
        "search_user": "unset",
        "topups": [],
        "candidates": [
            CandidateDocument(document_id="new", kind=QuestionKind.DOCUMENT)
        ],
    }
    set_ = monkeypatch.setattr
    set_(tasks, "is_enabled", lambda: True)
    set_(tasks, "release_pool_flag", lambda t: state["released"].append(("pool", t)))
    set_(
        tasks,
        "release_topup_flag",
        lambda _t, u: state["released"].append(("topup", u)),
    )
    set_(tasks, "pool_lock", lambda _wait: nullcontext())
    set_(tasks, "load_pool", lambda **_kw: state["pool"])
    set_(tasks, "save_pool", lambda pool: state.update(saved=pool))
    set_(tasks, "get_session_with_current_tenant", MagicMock())
    set_(tasks, "get_live_document_ids", lambda _s, ids: set(ids))
    set_(tasks, "count_new_documents_since", lambda _s, _since: 0)
    set_(tasks, "count_candidate_documents", lambda _s, _ids: 30)
    set_(tasks, "worth_running", lambda *_a, **_kw: state["decision"])
    set_(tasks, "get_recently_active_users", lambda _s, _now: [])
    set_(tasks, "choose_documents", lambda *_a, **_kw: state["candidates"])
    set_(tasks, "fetch_chunks", lambda *_a: [])
    set_(tasks, "build_triage_clients", list)
    set_(tasks, "triage_chunks", MagicMock(return_value=[]))
    set_(tasks, "best_chunks_per_document", lambda t: t)
    set_(tasks, "build_writing_llms", lambda: [MagicMock()])
    state["write"] = MagicMock(return_value=[])
    set_(tasks, "write_questions", state["write"])
    set_(tasks, "load_settings", lambda: MagicMock(company_name="Acme"))

    def search(drafts: list[Any], user: User | None) -> list[PoolQuestion]:  # noqa: ARG001
        state["search_user"] = user
        return [_question("new")]

    set_(tasks, "run_search_test", search)
    set_(tasks, "load_user_record", lambda *_a, **_kw: UserRecord())
    set_(tasks, "topup_allowed", lambda *_a: True)
    set_(tasks, "record_topup", lambda u, *_a: state["topups"].append(u))
    return state


def _pool_task() -> None:
    # Typed loosely: celery's stubs do not know the task's keyword arguments.
    pool_task: Any = tasks.generate_suggested_questions_pool
    pool_task.run(tenant_id="tenant", reason="growth")


def test_pool_run_saves_the_merged_pool_and_records_the_run(
    run: dict[str, Any],
) -> None:
    _pool_task()

    saved: QuestionPool = run["saved"]
    assert {q.document_id for q in saved.questions} == {"old", "new"}
    assert len(saved.runs) == 1
    assert run["search_user"] is None  # a pool run searches the whole index
    assert run["released"] == [("pool", "tenant")]


def test_pool_run_skipped_makes_no_model_call(run: dict[str, Any]) -> None:
    run["decision"] = RunDecision(run=False, reason="running low, but too soon")

    _pool_task()

    run["write"].assert_not_called()
    assert run["saved"] is None


def test_pool_run_stops_when_another_run_holds_the_pool(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def busy(_wait: float) -> Any:
        raise CacheLockAcquisitionError("held")

    monkeypatch.setattr(tasks, "pool_lock", busy)
    retry = MagicMock()
    monkeypatch.setattr(tasks.generate_suggested_questions_pool, "retry", retry)

    _pool_task()

    retry.assert_not_called()
    assert run["saved"] is None


def test_pool_run_does_nothing_when_disabled(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "is_enabled", lambda: False)

    _pool_task()

    assert run["saved"] is None
    assert run["released"] == [("pool", "tenant")]  # the flag is still freed


def test_pool_run_retries_when_writing_fails(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        tasks, "write_questions", MagicMock(side_effect=RuntimeError("no model"))
    )
    retry = MagicMock(side_effect=Retry())
    monkeypatch.setattr(tasks.generate_suggested_questions_pool, "retry", retry)

    with pytest.raises(Retry):
        _pool_task()

    assert retry.call_args.kwargs["countdown"] == tasks.SQ_RUN_RETRY_DELAY_S
    assert run["saved"] is None


@pytest.fixture
def person(monkeypatch: pytest.MonkeyPatch) -> User:
    user = User(id=uuid4(), email="alice@co.com", is_active=True)
    monkeypatch.setattr(tasks, "fetch_user_by_id", lambda _s, _id: user)
    return user


def _topup(user: User) -> None:
    topup_task: Any = tasks.generate_suggested_questions_for_user
    topup_task.run(tenant_id="tenant", user_id=str(user.id))


def test_topup_searches_as_the_person_and_records_the_topup(
    run: dict[str, Any], person: User
) -> None:
    _topup(person)

    assert run["search_user"] is person
    assert run["topups"] == [person.id]
    assert {q.document_id for q in run["saved"].questions} == {"old", "new"}
    assert run["saved"].runs == []  # top-ups do not count as pool runs


@pytest.mark.usefixtures("run")
def test_topup_retries_soon_when_the_pool_is_busy(
    person: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    def busy(_wait: float) -> Any:
        raise CacheLockAcquisitionError("held")

    monkeypatch.setattr(tasks, "pool_lock", busy)
    retry = MagicMock(side_effect=Retry())
    monkeypatch.setattr(tasks.generate_suggested_questions_for_user, "retry", retry)

    with pytest.raises(Retry):
        _topup(person)

    assert retry.call_args.kwargs["countdown"] == tasks.SQ_LOCK_BUSY_RETRY_S


@pytest.mark.parametrize("cause", ["limits used", "nothing new"])
def test_topup_stops_before_any_model_call(
    run: dict[str, Any], person: User, monkeypatch: pytest.MonkeyPatch, cause: str
) -> None:
    if cause == "limits used":
        monkeypatch.setattr(tasks, "topup_allowed", lambda *_a: False)
    else:
        run["candidates"] = []

    _topup(person)

    run["write"].assert_not_called()
    assert run["topups"] == []
    assert run["saved"] is None


def test_a_failed_flag_release_does_not_stop_the_run(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def cache_down(_tenant_id: str) -> None:
        raise ConnectionError("cache down")

    monkeypatch.setattr(tasks, "release_pool_flag", cache_down)

    _pool_task()

    assert run["saved"] is not None


def test_an_unknown_trial_status_skips_the_run_quietly(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreadable() -> bool:
        raise RuntimeError("settings store down")

    monkeypatch.setattr(tasks, "is_enabled", unreadable)
    retry = MagicMock()
    monkeypatch.setattr(tasks.generate_suggested_questions_pool, "retry", retry)

    _pool_task()

    assert run["saved"] is None
    retry.assert_not_called()
