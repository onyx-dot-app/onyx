from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
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
from onyx.tracing.framework.create import get_current_trace
from onyx.tracing.framework.provider import DefaultTraceProvider
from onyx.tracing.framework.setup import get_trace_provider, set_trace_provider
from onyx.tracing.framework.traces import Trace, TraceContentMode


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
        "found": [_question("new")],
        "records": {},
        "private_saved": {},
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
    # The person who asked for a run, and what they may open: everything.
    set_(
        tasks,
        "fetch_user_by_id",
        lambda _s, user_id: User(id=user_id, email="someone@co.com", is_active=True),
    )
    set_(tasks, "get_user_external_group_ids", lambda *_a: [])
    set_(tasks, "get_censoring_enabled_sources", set)
    set_(tasks, "get_visible_document_ids", lambda _s, _u, _g, ids, _c: set(ids))
    set_(tasks, "count_candidate_documents", lambda _s, _ids: 30)
    set_(tasks, "worth_running", lambda *_a, **_kw: state["decision"])
    set_(tasks, "get_recently_active_users", lambda _s, _now: [])
    set_(tasks, "choose_documents", lambda *_a, **_kw: state["candidates"])
    state["chunks"] = [MagicMock(document_id="doc")]
    set_(tasks, "fetch_chunks", lambda *_a: list(state["chunks"]))
    set_(tasks, "build_writing_llms", lambda: [MagicMock()])
    state["write"] = MagicMock(return_value=[])
    set_(tasks, "write_questions", state["write"])
    set_(tasks, "load_settings", lambda: MagicMock(company_name="Acme"))

    def search(
        drafts: list[Any],  # noqa: ARG001
        user: User | None,
        timeout_s: float | None = None,
    ) -> list[PoolQuestion]:
        state["search_user"] = user
        state["search_timeout"] = timeout_s
        return list(state["found"])

    set_(tasks, "run_search_test", search)
    set_(
        tasks,
        "load_user_record",
        lambda user_id, **_kw: state["records"].get(user_id, UserRecord()),
    )
    set_(
        tasks,
        "save_private_questions",
        lambda user_id, added, _live, _now: state["private_saved"].update(
            {user_id: [q.document_id for q in added]}
        ),
    )
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


def _pool_task_for(requester_id: str) -> None:
    pool_task: Any = tasks.generate_suggested_questions_pool
    pool_task.run(tenant_id="tenant", reason="person_short", requester_id=requester_id)


def test_a_run_for_a_person_who_is_no_longer_short_is_skipped(
    run: dict[str, Any],
) -> None:
    alice = uuid4()
    run["pool"] = QuestionPool(
        questions=[_question(f"s-{n}") for n in range(tasks.SQ_SHARED_REFRESH_AT + 1)]
    )

    _pool_task_for(str(alice))

    run["write"].assert_not_called()
    assert run["saved"] is None


def test_questions_the_requester_may_not_open_do_not_count(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    run["pool"] = QuestionPool(
        questions=[_question(f"s-{n}") for n in range(tasks.SQ_SHARED_REFRESH_AT + 1)]
    )
    # One question's document became private: the person is short again.
    monkeypatch.setattr(
        tasks,
        "get_visible_document_ids",
        lambda _s, _u, _g, ids, _c: set(ids) - {"s-0"},
    )

    _pool_task_for(str(uuid4()))

    assert run["saved"] is not None


def test_a_run_for_a_person_who_is_gone_is_skipped(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "fetch_user_by_id", lambda *_a: None)

    _pool_task_for(str(uuid4()))

    run["write"].assert_not_called()
    assert run["saved"] is None


def test_a_run_for_a_short_person_drops_their_used_questions_first(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = uuid4()
    run["pool"] = QuestionPool(questions=[_question("old")])
    run["records"][alice] = UserRecord(used=["old"])
    evicted: list[Any] = []
    merge = tasks.merge_questions
    monkeypatch.setattr(
        tasks,
        "merge_questions",
        lambda *a, **kw: evicted.append(kw.get("evict_first")) or merge(*a, **kw),
    )

    _pool_task_for(str(alice))

    assert evicted == [{"old"}]
    assert run["saved"] is not None


def test_pool_run_skipped_makes_no_model_call(run: dict[str, Any]) -> None:
    run["decision"] = RunDecision(run=False, reason="running low, but too soon")

    _pool_task()

    run["write"].assert_not_called()
    assert run["saved"] is None


def _busy(_wait: float) -> Any:
    raise CacheLockAcquisitionError("held")


def test_pool_run_retries_later_when_another_run_holds_the_pool(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "pool_lock", _busy)
    retry = MagicMock(side_effect=Retry())
    monkeypatch.setattr(tasks.generate_suggested_questions_pool, "retry", retry)

    with pytest.raises(Retry):
        _pool_task()

    assert retry.call_args.kwargs["countdown"] == tasks.SQ_POOL_BUSY_RETRY_S
    assert retry.call_args.kwargs["kwargs"]["reason"] == "growth"
    assert run["saved"] is None


def test_a_busy_pool_on_the_last_retry_stops_quietly(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    task: Any = tasks.generate_suggested_questions_pool
    monkeypatch.setattr(tasks, "pool_lock", _busy)
    retry = MagicMock()
    monkeypatch.setattr(task, "retry", retry)
    task.push_request(retries=task.max_retries)
    try:
        task.run(tenant_id="tenant", reason="growth")
    finally:
        task.pop_request()

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


def _nothing_searchable(*_a: Any) -> list[Any]:
    raise tasks.NothingSearchableYet("no chunks yet")


def test_pool_run_retries_when_its_documents_are_not_searchable_yet(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "fetch_chunks", _nothing_searchable)
    retry = MagicMock(side_effect=Retry())
    monkeypatch.setattr(tasks.generate_suggested_questions_pool, "retry", retry)

    with pytest.raises(Retry):
        _pool_task()

    assert retry.call_args.kwargs["countdown"] == tasks.SQ_RUN_RETRY_DELAY_S
    run["write"].assert_not_called()
    # No run is recorded, so a first run stays a first run.
    assert run["saved"] is None


def test_unsearchable_documents_on_the_last_retry_record_no_run(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    task: Any = tasks.generate_suggested_questions_pool
    monkeypatch.setattr(tasks, "fetch_chunks", _nothing_searchable)
    retry = MagicMock()
    monkeypatch.setattr(task, "retry", retry)
    task.push_request(retries=task.max_retries)
    try:
        task.run(tenant_id="tenant", reason="first_run")
    finally:
        task.pop_request()

    retry.assert_not_called()
    assert run["saved"] is None


def test_a_run_whose_chunks_were_all_junk_is_recorded(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The index answered, so retrying would read the same junk again.
    monkeypatch.setattr(tasks, "fetch_chunks", lambda *_a: [])

    _pool_task()

    assert len(run["saved"].runs) == 1


def test_a_retry_leaves_the_queued_flag_alone(run: dict[str, Any]) -> None:
    # The first delivery freed it; a flag set now belongs to a newer request.
    task: Any = tasks.generate_suggested_questions_pool
    task.push_request(retries=1)
    try:
        task.run(tenant_id="tenant", reason="growth")
    finally:
        task.pop_request()

    assert run["released"] == []
    assert run["saved"] is not None


@pytest.fixture
def person(run: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> User:
    """Alice, whose private bucket chose the document the run writes about."""
    user = User(id=uuid4(), email="alice@co.com", is_active=True)
    monkeypatch.setattr(tasks, "fetch_user_by_id", lambda _s, _id: user)
    run["candidates"] = [
        CandidateDocument(
            document_id="new", kind=QuestionKind.DOCUMENT, owner_ids=[user.id]
        )
    ]
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
    # A top-up fills the person's private shelf; the shared shelf is untouched.
    assert run["private_saved"] == {person.id: ["new"]}
    assert run["saved"] is None


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


@pytest.mark.parametrize("cause", ["limits used", "nothing new", "has enough"])
def test_topup_stops_before_any_model_call(
    run: dict[str, Any], person: User, monkeypatch: pytest.MonkeyPatch, cause: str
) -> None:
    if cause == "limits used":
        monkeypatch.setattr(tasks, "topup_allowed", lambda *_a: False)
    elif cause == "nothing new":
        run["candidates"] = []
    else:
        unused = tasks.SQ_PRIVATE_REFILL_AT + 1
        run["records"][person.id] = UserRecord(
            questions=[_question(f"mine-{n}") for n in range(unused)]
        )

    _topup(person)

    run["write"].assert_not_called()
    assert run["topups"] == []
    assert run["private_saved"] == {}


def test_questions_the_person_may_not_open_do_not_count_toward_enough(
    run: dict[str, Any], person: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    questions = [_question(f"mine-{n}") for n in range(tasks.SQ_PRIVATE_REFILL_AT + 1)]
    run["records"][person.id] = UserRecord(questions=questions)
    monkeypatch.setattr(
        tasks,
        "get_visible_document_ids",
        lambda _s, _u, _g, ids, _c: set(ids) - {"mine-0"},
    )

    _topup(person)

    assert run["private_saved"] == {person.id: ["new"]}


def test_used_questions_do_not_count_toward_enough(
    run: dict[str, Any], person: User
) -> None:
    questions = [_question(f"mine-{n}") for n in range(tasks.SQ_PRIVATE_REFILL_AT + 1)]
    run["records"][person.id] = UserRecord(questions=questions, used=[questions[0].id])

    _topup(person)

    assert run["private_saved"] == {person.id: ["new"]}


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


def _old_question(document_id: str) -> PoolQuestion:
    question = _question(document_id)
    return question.model_copy(
        update={"created_at": question.created_at - timedelta(days=8)}
    )


def test_expired_questions_free_their_documents(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    run["pool"] = QuestionPool(questions=[_question("fresh"), _old_question("expired")])
    excluded: list[set[str]] = []
    monkeypatch.setattr(
        tasks,
        "choose_documents",
        lambda _s, _people, shared_exclude, _private, **_kw: (
            excluded.append(set(shared_exclude)) or run["candidates"]
        ),
    )

    _pool_task()

    assert excluded == [{"fresh"}]
    assert {q.document_id for q in run["saved"].questions} == {"fresh", "new"}


def test_a_pool_run_puts_each_question_on_its_shelf(run: dict[str, Any]) -> None:
    alice, bob = uuid4(), uuid4()
    run["candidates"] = [
        CandidateDocument(document_id="handbook", kind=QuestionKind.DOCUMENT),
        CandidateDocument(
            document_id="team-plan",
            kind=QuestionKind.DOCUMENT,
            owner_ids=[alice, bob],
        ),
        CandidateDocument(
            document_id="alice-notes", kind=QuestionKind.USER_FILE, owner_ids=[alice]
        ),
    ]
    run["found"] = [_question(d) for d in ("handbook", "team-plan", "alice-notes")]

    _pool_task()

    assert {q.document_id for q in run["saved"].questions} == {"old", "handbook"}
    assert run["private_saved"] == {
        alice: ["team-plan", "alice-notes"],
        bob: ["team-plan"],
    }


def test_a_failed_private_save_leaves_the_run_unrecorded(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = uuid4()
    run["candidates"] = [
        CandidateDocument(
            document_id="new", kind=QuestionKind.DOCUMENT, owner_ids=[alice]
        )
    ]

    def lock_timed_out(*_args: Any) -> None:
        raise CacheLockAcquisitionError("person's record is busy")

    monkeypatch.setattr(tasks, "save_private_questions", lock_timed_out)
    retry = MagicMock(side_effect=Retry())
    monkeypatch.setattr(tasks.generate_suggested_questions_pool, "retry", retry)

    with pytest.raises(Retry):
        _pool_task()

    # The pool, with this run's record, is not saved, so the retry may run.
    assert run["saved"] is None


def test_each_persons_shelf_is_excluded_for_them(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = User(id=uuid4(), email="alice@co.com", is_active=True)
    monkeypatch.setattr(tasks, "get_recently_active_users", lambda _s, _now: [alice])
    run["records"][alice.id] = UserRecord(
        questions=[_question("on-her-shelf"), _old_question("expired")]
    )
    excluded: list[Any] = []
    monkeypatch.setattr(
        tasks,
        "choose_documents",
        lambda _s, _people, _shared, private, **_kw: (
            excluded.append(private) or run["candidates"]
        ),
    )

    _pool_task()

    assert excluded == [{alice.id: {"on-her-shelf"}}]


def test_passages_keep_the_candidates_order(run: dict[str, Any]) -> None:
    run["candidates"] = [
        CandidateDocument(document_id=d, kind=QuestionKind.DOCUMENT)
        for d in ("private", "shared")
    ]
    run["chunks"] = [MagicMock(document_id=d) for d in ("shared", "private")]

    _pool_task()

    written = run["write"].call_args.args[0]
    assert [chunk.document_id for chunk in written] == ["private", "shared"]
    # The writing calls leave the search test its share of the budget.
    write_timeout = run["write"].call_args.kwargs["timeout_s"]
    assert 0 < write_timeout <= tasks.SQ_RUN_BUDGET_S - tasks.SQ_SEARCH_TEST_RESERVE_S
    assert run["search_timeout"] is not None


def test_no_save_when_the_pool_lock_may_have_expired(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "SQ_POOL_LOCK_HELD_S", 0.0)
    monkeypatch.setattr(tasks, "SQ_SAVE_MARGIN_S", 0.0)
    retry = MagicMock(side_effect=Retry())
    monkeypatch.setattr(tasks.generate_suggested_questions_pool, "retry", retry)

    with pytest.raises(Retry):
        _pool_task()

    assert run["saved"] is None


def test_the_lease_is_checked_before_each_private_write(
    run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    alice, bob = uuid4(), uuid4()
    run["candidates"] = [
        CandidateDocument(document_id=d, kind=QuestionKind.DOCUMENT, owner_ids=[o])
        for d, o in (("a", alice), ("b", bob))
    ]
    run["found"] = [_question("a"), _question("b")]
    written: list[Any] = []

    def write_that_uses_up_the_lease(user_id: Any, *_args: Any) -> None:
        written.append(user_id)
        monkeypatch.setattr(tasks, "SQ_POOL_LOCK_HELD_S", 0.0)
        monkeypatch.setattr(tasks, "SQ_SAVE_MARGIN_S", 0.0)

    monkeypatch.setattr(tasks, "save_private_questions", write_that_uses_up_the_lease)
    retry = MagicMock(side_effect=Retry())
    monkeypatch.setattr(tasks.generate_suggested_questions_pool, "retry", retry)

    with pytest.raises(Retry):
        _pool_task()

    assert written == [alice]
    assert run["saved"] is None


def test_a_retry_finishes_its_recorded_topup(
    run: dict[str, Any], person: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The first attempt recorded the top-up, so the gap check would refuse it.
    monkeypatch.setattr(tasks, "topup_allowed", lambda *_a: False)
    topup_task: Any = tasks.generate_suggested_questions_for_user

    topup_task.run(tenant_id="tenant", user_id=str(person.id), recorded=True)

    assert run["topups"] == []  # not counted twice
    assert run["private_saved"] == {person.id: ["new"]}


def test_a_failed_topup_retries_as_recorded(
    run: dict[str, Any], person: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    run["write"].side_effect = RuntimeError("no model")
    retry = MagicMock(side_effect=Retry())
    monkeypatch.setattr(tasks.generate_suggested_questions_for_user, "retry", retry)

    with pytest.raises(Retry):
        _topup(person)

    assert run["topups"] == [person.id]
    assert retry.call_args.kwargs["kwargs"]["recorded"] is True


def test_model_calls_run_in_a_metadata_only_trace(run: dict[str, Any]) -> None:
    """Usage tracking records a model call only inside a trace; without one
    a run's model spend is never recorded."""
    run["candidates"] = [
        CandidateDocument(document_id="doc", kind=QuestionKind.DOCUMENT)
    ]
    traces: list[Trace | None] = []

    def write(*_args: Any, **_kwargs: Any) -> list[Any]:
        traces.append(get_current_trace())
        return []

    run["write"].side_effect = write
    original = get_trace_provider()
    set_trace_provider(DefaultTraceProvider())
    try:
        _pool_task()
    finally:
        set_trace_provider(original)

    assert len(traces) == 1 and traces[0] is not None
    assert traces[0].content_mode == TraceContentMode.METADATA_ONLY
