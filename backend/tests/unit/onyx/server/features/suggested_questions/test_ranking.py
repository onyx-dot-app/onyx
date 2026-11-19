from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.configs.constants import DocumentSource
from onyx.db.models import User
from onyx.server.features.suggested_questions import ranking
from onyx.server.features.suggested_questions.models import (
    CandidateDocument,
    PoolQuestion,
    QuestionKind,
    QuestionPool,
    RefreshReason,
    SuggestionsState,
    UserRecord,
)

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _question(document_id: str, age: timedelta = timedelta(0)) -> PoolQuestion:
    return PoolQuestion(
        id=f"q-{document_id}",
        text=f"About {document_id}?",
        kind=QuestionKind.DOCUMENT,
        document_id=document_id,
        source_type=DocumentSource.GOOGLE_DRIVE,
        search_position=0,
        best_for=None,
        created_at=NOW - age,
    )


def test_usable_questions_skip_used_hidden_and_old() -> None:
    questions = [
        _question("ok"),
        _question("used"),
        _question("hidden"),
        _question("old", age=timedelta(days=8)),
    ]
    record = UserRecord(used=["q-used"])

    usable = ranking.usable_questions(questions, record, {"ok", "used", "old"}, NOW)

    assert [q.document_id for q in usable] == ["ok"]


def test_pick_shows_private_first_and_at_most_four() -> None:
    private = [_question("mine-1"), _question("mine-2")]
    shared = [_question(f"shared-{n}") for n in range(5)]

    shown = ranking.pick_questions(private, shared, seed=7)

    assert len(shown) == 4
    assert [q.private for q in shown] == [True, True, False, False]
    assert {q.id for q in shown[:2]} == {"q-mine-1", "q-mine-2"}
    assert shown[0].message.startswith("About ")


def test_pick_is_stable_for_a_page_load_and_rotates_across_loads() -> None:
    shared = [_question(f"shared-{n}") for n in range(8)]

    def ids(seed: int) -> list[str]:
        return [q.id for q in ranking.pick_questions([], shared, seed=seed)]

    assert ids(1) == ids(1)
    assert len({tuple(ids(seed)) for seed in range(10)}) > 1


@pytest.fixture
def person() -> User:
    return User(id=uuid4(), email="alice@co.com", is_active=True)


@pytest.fixture
def chat(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A playground company; every document is visible, and nothing is asked
    for unless a test lets it."""
    state: dict[str, Any] = {
        "pool": QuestionPool(),
        "record": UserRecord(),
        "seen": [],
        "requested": [],
        "pool_requests": [],
        "topups": [],
        "pool_allowed": True,
        "candidates": [
            CandidateDocument(document_id="mine", kind=QuestionKind.USER_FILE)
        ],
        "has_documents": True,
    }
    set_ = monkeypatch.setattr
    set_(ranking, "is_enabled", lambda: True)
    set_(ranking, "load_pool", lambda: state["pool"])
    set_(ranking, "load_user_record", lambda _id: state["record"])

    def seen(_id: Any, now: datetime) -> UserRecord:
        state["seen"].append(now)
        return state["record"]

    def requested(_id: Any, now: datetime) -> UserRecord:
        state["requested"].append(now)
        return state["record"].model_copy(update={"requested_at": now})

    set_(ranking, "record_seen", seen)
    set_(ranking, "record_requested", requested)
    set_(ranking, "get_user_external_group_ids", lambda *_a: [])
    set_(ranking, "get_censoring_enabled_sources", set)
    set_(
        ranking,
        "get_visible_document_ids",
        lambda _s, _u, _g, ids, _censored: set(ids),
    )
    set_(ranking, "get_session_with_current_tenant", MagicMock())
    set_(ranking, "has_visible_documents", lambda *_a: state["has_documents"])

    def pool_refresh(_t: str, reason: RefreshReason, requester_id: Any) -> bool:
        state["pool_requests"].append((reason, requester_id))
        return state["pool_allowed"]

    set_(ranking, "request_pool_refresh", pool_refresh)
    set_(
        ranking,
        "request_user_topup",
        lambda _t, user_id, *_a: state["topups"].append(user_id) or True,
    )
    set_(ranking, "choose_documents", lambda *_a, **_kw: state["candidates"])
    return state


def _open(person: User, poll: bool = False) -> Any:
    return ranking.get_suggestions(
        MagicMock(), person, "tenant", seed=1, poll=poll, now=NOW
    )


def test_a_person_short_of_shared_questions_asks_for_a_pool_run(
    chat: dict[str, Any], person: User
) -> None:
    chat["pool"] = QuestionPool(questions=[_question("handbook")])

    result = _open(person)

    assert chat["pool_requests"] == [(RefreshReason.PERSON_SHORT, person.id)]
    assert chat["topups"] == []  # the pool run fills private shelves too
    assert chat["seen"] == [NOW] and chat["requested"] == [NOW]
    assert [q.id for q in result.questions] == ["q-handbook"]
    assert result.state == SuggestionsState.PREPARING


def test_a_top_up_when_no_pool_run_is_allowed_now(
    chat: dict[str, Any], person: User
) -> None:
    chat["pool_allowed"] = False

    _open(person)

    assert chat["topups"] == [person.id]


def test_no_top_up_when_there_is_nothing_new_to_write_about(
    chat: dict[str, Any], person: User
) -> None:
    chat["pool_allowed"] = False
    chat["candidates"] = []
    chat["has_documents"] = False

    result = _open(person)

    assert chat["topups"] == [] and chat["requested"] == []
    assert result.state == SuggestionsState.NO_DOCUMENTS


def test_enough_questions_asks_for_nothing(chat: dict[str, Any], person: User) -> None:
    chat["pool"] = QuestionPool(questions=[_question(f"s-{n}") for n in range(5)])
    chat["record"] = UserRecord(questions=[_question(f"p-{n}") for n in range(7)])

    result = _open(person)

    assert chat["pool_requests"] == [] and chat["topups"] == []
    assert len(result.questions) == 4
    assert result.state == SuggestionsState.READY


def test_a_poll_only_reads(chat: dict[str, Any], person: User) -> None:
    chat["record"] = UserRecord(requested_at=NOW - timedelta(seconds=30))

    result = _open(person, poll=True)

    assert chat["seen"] == [] and chat["pool_requests"] == []
    assert result.state == SuggestionsState.PREPARING


def test_preparing_ends_after_a_while(chat: dict[str, Any], person: User) -> None:
    chat["record"] = UserRecord(requested_at=NOW - timedelta(minutes=5))

    assert _open(person, poll=True).state == SuggestionsState.READY


def test_off_the_playground_nothing_happens(
    chat: dict[str, Any], person: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ranking, "is_enabled", lambda: False)

    result = _open(person)

    assert result.questions == [] and result.state == SuggestionsState.READY
    assert chat["seen"] == []


def test_a_failed_run_request_does_not_fail_the_chat_page(
    chat: dict[str, Any], person: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat["pool_allowed"] = False
    monkeypatch.setattr(
        ranking, "choose_documents", MagicMock(side_effect=RuntimeError("db down"))
    )

    result = _open(person)

    assert chat["requested"] == []
    assert result.state == SuggestionsState.READY


def test_the_pick_ignores_the_order_the_shelf_comes_in() -> None:
    shared = [_question(f"shared-{n}") for n in range(6)]

    def ids(order: list[PoolQuestion]) -> list[str]:
        return [q.id for q in ranking.pick_questions([], order, seed=3)]

    assert ids(shared) == ids(list(reversed(shared)))


def test_a_failed_request_record_still_returns_the_questions(
    chat: dict[str, Any], person: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat["pool"] = QuestionPool(questions=[_question("handbook")])
    monkeypatch.setattr(
        ranking, "record_requested", MagicMock(side_effect=RuntimeError("kv down"))
    )

    result = _open(person)

    assert chat["pool_requests"]  # the run was still asked for
    assert [q.id for q in result.questions] == ["q-handbook"]


def test_questions_the_person_may_not_open_are_not_shown(
    chat: dict[str, Any], person: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat["pool"] = QuestionPool(questions=[_question("open"), _question("censored")])
    asked: list[Any] = []

    def visible(_s: Any, _u: Any, _g: Any, ids: list[str], censored: Any) -> set[str]:
        asked.append(censored)
        return {i for i in ids if i != "censored"}

    monkeypatch.setattr(ranking, "get_visible_document_ids", visible)
    monkeypatch.setattr(
        ranking, "get_censoring_enabled_sources", lambda: {DocumentSource.SALESFORCE}
    )

    result = _open(person)

    assert [q.id for q in result.questions] == ["q-open"]
    assert asked == [{DocumentSource.SALESFORCE}]
