"""Tests for the NDJSON parser's milestone + message-id extraction."""

from __future__ import annotations

import json

from onyx_client.stream_parser import ChatStreamAnalyzer
from onyx_client.stream_parser import FIRST_ANSWER_TOKEN
from onyx_client.stream_parser import FIRST_PACKET


def _feed_all(analyzer: ChatStreamAnalyzer, lines: list[str]) -> list[str]:
    hit: list[str] = []
    for line in lines:
        hit.extend(analyzer.feed(line))
    return hit


def test_captures_reserved_assistant_message_id() -> None:
    analyzer = ChatStreamAnalyzer()
    _feed_all(
        analyzer,
        [
            json.dumps({"reserved_assistant_message_id": 4321}),
            json.dumps({"obj": {"type": "message_start", "content": "hi"}}),
            json.dumps({"obj": {"type": "message_delta", "content": " there"}}),
            json.dumps({"obj": {"type": "stop"}}),
        ],
    )
    assert analyzer.summary.reserved_assistant_message_id == 4321
    assert analyzer.completed_ok()


def test_message_id_absent_is_none() -> None:
    analyzer = ChatStreamAnalyzer()
    _feed_all(
        analyzer,
        [
            json.dumps({"obj": {"type": "message_start", "content": "hi"}}),
            json.dumps({"obj": {"type": "stop"}}),
        ],
    )
    assert analyzer.summary.reserved_assistant_message_id is None


def test_milestones_fire_once_in_order() -> None:
    analyzer = ChatStreamAnalyzer()
    first = analyzer.feed(json.dumps({"reserved_assistant_message_id": 1}))
    assert first == [FIRST_PACKET]
    # First content packet fires FIRST_ANSWER_TOKEN; a later one does not refire.
    assert FIRST_ANSWER_TOKEN in analyzer.feed(
        json.dumps({"obj": {"type": "message_start", "content": "x"}})
    )
    assert FIRST_ANSWER_TOKEN not in analyzer.feed(
        json.dumps({"obj": {"type": "message_delta", "content": "y"}})
    )


def test_error_packet_marks_failure() -> None:
    analyzer = ChatStreamAnalyzer()
    _feed_all(analyzer, [json.dumps({"error": "boom"})])
    assert not analyzer.completed_ok()
    assert "boom" in analyzer.failure_reason()
