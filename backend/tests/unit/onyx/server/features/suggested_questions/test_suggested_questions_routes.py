from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from onyx.configs.constants import ANONYMOUS_USER_UUID, DEFAULT_PERSONA_ID
from onyx.db.models import User
from onyx.server.features.suggested_questions import api
from onyx.server.features.suggested_questions.config import SQ_QUESTION_ID_MAX_BYTES
from onyx.server.features.suggested_questions.models import (
    MarkUsedRequest,
    PersonSuggestions,
    ShownQuestion,
    SuggestionsState,
)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"seen": [], "used": [], "picks": []}
    monkeypatch.setattr(api, "is_enabled", lambda: True)
    monkeypatch.setattr(
        api, "record_seen", lambda user_id, _now: state["seen"].append(user_id)
    )
    monkeypatch.setattr(
        api, "mark_used", lambda user_id, qid: state["used"].append((user_id, qid))
    )
    monkeypatch.setattr(api, "get_current_tenant_id", lambda: "tenant")

    def pick(
        _s: Any, user: User, tenant_id: str, seed: int, poll: bool, **_kw: Any
    ) -> PersonSuggestions:
        state["picks"].append((user.id, tenant_id, seed, poll))
        return PersonSuggestions(
            questions=[ShownQuestion(id="q1", message="How?", private=False)],
            state=SuggestionsState.READY,
        )

    monkeypatch.setattr(api, "get_suggestions", pick)
    return state


def _user() -> User:
    return User(id=uuid4(), email="alice@co.com", is_active=True)


def _get(user: User, agent_id: int = DEFAULT_PERSONA_ID, poll: bool = False) -> Any:
    return api.get_suggested_questions(
        agent_id=agent_id, seed=7, poll=poll, user=user, db_session=MagicMock()
    )


def test_the_default_agent_gets_the_persons_questions(calls: dict[str, Any]) -> None:
    alice = _user()

    result = _get(alice)

    assert [q.id for q in result.questions] == ["q1"]
    assert calls["picks"] == [(alice.id, "tenant", 7, False)]


def test_a_custom_agent_records_the_visit_but_shows_nothing(
    calls: dict[str, Any],
) -> None:
    alice = _user()

    result = _get(alice, agent_id=DEFAULT_PERSONA_ID + 1)

    assert result.questions == [] and result.state == SuggestionsState.READY
    assert calls["seen"] == [alice.id]
    assert calls["picks"] == []


def test_a_poll_on_a_custom_agent_records_nothing(calls: dict[str, Any]) -> None:
    _get(_user(), agent_id=DEFAULT_PERSONA_ID + 1, poll=True)

    assert calls["seen"] == []


def test_the_anonymous_user_gets_nothing(calls: dict[str, Any]) -> None:
    anonymous = User(id=UUID(ANONYMOUS_USER_UUID), email="anonymous@onyx.app")

    result = _get(anonymous)

    assert result.questions == []
    assert calls["picks"] == [] and calls["seen"] == []


def test_a_click_marks_the_question_used(calls: dict[str, Any]) -> None:
    alice = _user()

    api.mark_suggested_question_used(MarkUsedRequest(question_id="q1"), alice)

    assert calls["used"] == [(alice.id, "q1")]


def test_a_click_off_the_playground_stores_nothing(
    calls: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "is_enabled", lambda: False)

    api.mark_suggested_question_used(MarkUsedRequest(question_id="q1"), _user())

    assert calls["used"] == []


def test_a_click_id_is_limited_in_bytes_not_characters() -> None:
    # "€" takes 3 bytes, so this is over the limit in fewer characters.
    over = "€" * (SQ_QUESTION_ID_MAX_BYTES // 3 + 1)

    with pytest.raises(ValidationError):
        MarkUsedRequest(question_id=over)
    assert MarkUsedRequest(question_id="a" * SQ_QUESTION_ID_MAX_BYTES).question_id
