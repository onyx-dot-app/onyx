"""A thumbs up or down reaches the fleet as a vote with a digest id and a channel,
and feedback that is only text or a follow-up request sends nothing."""

from unittest.mock import Mock

import pytest

from onyx.configs.constants import MessageType
from onyx.db import feedback
from onyx.server.query_and_chat.models import MessageOrigin
from onyx.utils import fleet_telemetry as fleet
from shared_configs.contextvars import get_current_tenant_id
from tests.utils.fleet_telemetry import make_sender


@pytest.fixture
def sender(monkeypatch: pytest.MonkeyPatch) -> fleet.BoundedTelemetry:
    enrolled: fleet.BoundedTelemetry = make_sender()
    monkeypatch.setattr(fleet, "_client", enrolled)
    return enrolled


def _assistant_message() -> Mock:
    message: Mock = Mock()
    message.message_type = MessageType.ASSISTANT
    return message


def _record(
    monkeypatch: pytest.MonkeyPatch,
    *,
    is_positive: bool | None,
    origin: MessageOrigin = MessageOrigin.WEBAPP,
    db_session: Mock | None = None,
) -> None:
    monkeypatch.setattr(
        feedback, "get_chat_message", lambda **_kwargs: _assistant_message()
    )
    feedback.create_chat_message_feedback(
        is_positive=is_positive,
        feedback_text="PRIVATE words",
        chat_message_id=7,
        user_id=None,
        db_session=db_session or Mock(),
        origin=origin,
    )


@pytest.mark.parametrize(
    "origin,channel", [(MessageOrigin.WEBAPP, "web"), (MessageOrigin.SLACKBOT, "slack")]
)
def test_a_vote_reports_its_channel_and_a_digest_only(
    monkeypatch: pytest.MonkeyPatch,
    sender: fleet.BoundedTelemetry,
    origin: MessageOrigin,
    channel: str,
) -> None:
    _record(monkeypatch, is_positive=False, origin=origin)
    (event,) = sender._take_batch()
    assert event["event_type"] == "feedback"
    assert event["data"] == {
        "feedback_id": fleet.fingerprint(f"{get_current_tenant_id()}:7"),
        "positive": False,
        "channel": channel,
    }


def test_the_same_answer_keeps_its_id_across_votes(
    monkeypatch: pytest.MonkeyPatch, sender: fleet.BoundedTelemetry
) -> None:
    _record(monkeypatch, is_positive=True)
    _record(monkeypatch, is_positive=False)
    first, second = sender._take_batch()
    assert first["data"]["feedback_id"] == second["data"]["feedback_id"]
    assert first["event_id"] != second["event_id"]


def test_feedback_without_a_vote_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, sender: fleet.BoundedTelemetry
) -> None:
    _record(monkeypatch, is_positive=None)
    assert sender._take_batch() == []


def test_a_vote_that_fails_to_save_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, sender: fleet.BoundedTelemetry
) -> None:
    db_session: Mock = Mock()
    db_session.commit.side_effect = RuntimeError("PRIVATE database error")
    with pytest.raises(RuntimeError):
        _record(monkeypatch, is_positive=True, db_session=db_session)
    assert sender._take_batch() == []
