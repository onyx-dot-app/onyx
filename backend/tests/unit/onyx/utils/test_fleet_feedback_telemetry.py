"""A thumbs up or down reaches the fleet as a vote with a digest id and a channel,
and feedback that is only text or a follow-up request sends nothing."""

from typing import Any
from unittest.mock import Mock

import pytest

from onyx.configs.constants import MessageType
from onyx.db import feedback
from onyx.utils import fleet_telemetry as fleet
from tests.utils.fleet_telemetry import make_sender


@pytest.fixture
def sender(monkeypatch: pytest.MonkeyPatch) -> fleet.BoundedTelemetry:
    enrolled: fleet.BoundedTelemetry = make_sender()
    monkeypatch.setattr(fleet, "_client", enrolled)
    return enrolled


def _assistant_message(*, from_slack: bool) -> Mock:
    message: Mock = Mock()
    message.message_type = MessageType.ASSISTANT
    message.chat_session.onyxbot_flow = from_slack
    return message


def _record(
    monkeypatch: pytest.MonkeyPatch,
    *,
    is_positive: bool | None,
    from_slack: bool = False,
) -> None:
    monkeypatch.setattr(
        feedback,
        "get_chat_message",
        lambda **_kwargs: _assistant_message(from_slack=from_slack),
    )
    feedback.create_chat_message_feedback(
        is_positive=is_positive,
        feedback_text="PRIVATE words",
        chat_message_id=7,
        user_id=None,
        db_session=Mock(),
        required_followup=None if is_positive is not None else True,
    )


@pytest.mark.parametrize("from_slack,channel", [(False, "web"), (True, "slack")])
def test_a_vote_reports_its_channel_and_a_digest_only(
    monkeypatch: pytest.MonkeyPatch,
    sender: fleet.BoundedTelemetry,
    from_slack: bool,
    channel: str,
) -> None:
    _record(monkeypatch, is_positive=False, from_slack=from_slack)
    (event,) = sender._take_batch()
    data: dict[str, Any] = event["data"]
    assert event["event_type"] == "feedback"
    assert data["positive"] is False and data["channel"] == channel
    assert len(data["feedback_id"]) == 64
    assert "PRIVATE" not in str(event)


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
