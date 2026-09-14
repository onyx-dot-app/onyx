"""Tests that one unretrievable message cannot discard a whole team's indexing.

`fetch_messages` paginates lazily, so a Graph error can surface on any `next()`.
The retrieval loop used to sit outside the `try`, so such an error propagated
out of the channel iterator, out of `load_from_checkpoint`, and ended the index
attempt for every remaining channel in the team -- reported as `0 documents,
1 failure`. Failures must now be yielded, not raised.
"""

from datetime import datetime, timezone
from typing import Iterator
from unittest.mock import MagicMock, patch

from requests.exceptions import HTTPError

from onyx.connectors.models import ConnectorFailure, Document
from onyx.connectors.teams.connector import _collect_documents_for_channel
from onyx.connectors.teams.models import Body, Message

_MODULE = "onyx.connectors.teams.connector"


def _message(message_id: str) -> Message:
    return Message(
        id=message_id,
        replyToId=None,
        subject=f"subject-{message_id}",
        from_=None,
        body=Body(content_type="html", content=f"<p>{message_id}</p>"),
        created_date_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_modified_date_time=None,
        last_edited_date_time=None,
        deleted_date_time=None,
        web_url=f"https://teams.example/{message_id}",
    )


def _http_error(status_code: int, code: str, detail: str) -> HTTPError:
    response = MagicMock()
    response.status_code = status_code
    response.text = detail
    response.json = MagicMock(return_value={"error": {"code": code, "message": detail}})
    error = HTTPError(f"{status_code} error")
    error.response = response
    return error


def _channel(channel_id: str = "channel-1") -> MagicMock:
    channel = MagicMock()
    channel.id = channel_id
    return channel


def _team(team_id: str = "team-1") -> MagicMock:
    team = MagicMock()
    team.id = team_id
    return team


def _entity_ids(failures: list[ConnectorFailure]) -> set[str]:
    entity_ids = set()
    for failure in failures:
        assert failure.failed_entity is not None
        entity_ids.add(failure.failed_entity.entity_id)
    return entity_ids


def _collect(
    messages: Iterator[Message],
    replies_side_effect: object = None,
) -> list[Document | None | ConnectorFailure]:
    """Run the channel collector with `fetch_messages`/`fetch_replies` stubbed.

    Document conversion is stubbed too so the assertions are about error
    handling rather than HTML parsing or permission lookups.
    """

    def _fake_replies(**_: object) -> Iterator[Message]:
        if isinstance(replies_side_effect, Exception):
            raise replies_side_effect
        return iter(())

    def _fake_convert(thread: list[Message], **_: object) -> Document:
        document = MagicMock(spec=Document)
        document.id = thread[0].id
        return document

    with (
        patch(f"{_MODULE}.fetch_messages", return_value=messages),
        patch(f"{_MODULE}.fetch_replies", side_effect=_fake_replies),
        patch(f"{_MODULE}._convert_thread_to_document", side_effect=_fake_convert),
    ):
        return list(
            _collect_documents_for_channel(
                graph_client=MagicMock(),
                team=_team(),
                channel=_channel(),
                start=0.0,
            )
        )


def _messages_then_raise(count: int, error: Exception) -> Iterator[Message]:
    for index in range(count):
        yield _message(f"message-{index}")
    raise error


def test_pagination_failure_is_yielded_not_raised() -> None:
    error = _http_error(403, "Forbidden", "Missing ChannelMessage.Read.All")

    results = _collect(messages=_messages_then_raise(0, error))

    assert len(results) == 1
    assert isinstance(results[0], ConnectorFailure)


def test_messages_retrieved_before_a_pagination_failure_are_kept() -> None:
    # The regression: a mid-pagination error discarded everything already
    # retrieved and the attempt reported 0 documents.
    error = _http_error(429, "TooManyRequests", "throttled")

    results = _collect(messages=_messages_then_raise(3, error))

    documents = [item for item in results if not isinstance(item, ConnectorFailure)]
    failures = [item for item in results if isinstance(item, ConnectorFailure)]
    assert len(documents) == 3
    assert len(failures) == 1


def test_pagination_failure_records_the_channel_and_http_status() -> None:
    error = _http_error(404, "NotFound", "channel gone")

    failure = next(
        item
        for item in _collect(messages=_messages_then_raise(1, error))
        if isinstance(item, ConnectorFailure)
    )

    assert failure.failed_entity is not None
    assert failure.failed_entity.entity_id == "channel-1"
    assert "404" in failure.failure_message
    assert "NotFound" in failure.failure_message
    assert failure.exception is error


def test_reply_failure_records_status_and_continues_to_next_message() -> None:
    error = _http_error(403, "Forbidden", "no access to replies")

    results = _collect(
        messages=iter([_message("message-0"), _message("message-1")]),
        replies_side_effect=error,
    )

    failures = [item for item in results if isinstance(item, ConnectorFailure)]
    # Both messages are attempted; neither aborts the channel.
    assert len(failures) == 2
    assert _entity_ids(failures) == {"message-0", "message-1"}
    assert all("403" in failure.failure_message for failure in failures)
    assert all("Forbidden" in failure.failure_message for failure in failures)


def test_healthy_channel_yields_a_document_per_message() -> None:
    results = _collect(messages=iter([_message("message-0"), _message("message-1")]))

    assert len(results) == 2
    assert not any(isinstance(item, ConnectorFailure) for item in results)
