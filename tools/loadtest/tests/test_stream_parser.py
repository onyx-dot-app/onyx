"""Milestone timing and counters follow current items, not update volume."""

import json

from onyx_client.stream_parser import (
    FIRST_ANSWER_TOKEN,
    FIRST_DR_PLAN,
    FIRST_PACKET,
    FIRST_RESEARCH_AGENT,
    FIRST_SEARCH_DOC,
    ChatStreamAnalyzer,
    _Body,
    _Metadata,
)


def packet(obj: _Body, part: str = "answer", parent: str | None = None) -> str:
    return json.dumps(
        {
            "identity": {
                "response_id": 1,
                "message_id": "root:0",
                "tool_call_id": None,
                "part_id": part,
                "parent_run_id": parent,
            },
            "obj": obj,
        }
    )


def test_answer_replacements_do_not_double_count_deltas() -> None:
    analyzer = ChatStreamAnalyzer()
    assert analyzer.feed(json.dumps({"reserved_assistant_message_id": 4321})) == [
        FIRST_PACKET
    ]
    analyzer.feed(
        packet(
            {
                "type": "item_update",
                "item": {"kind": "text", "purpose": "answer", "text": ""},
            }
        )
    )
    assert analyzer.feed(
        packet({"type": "item_delta", "delta": {"kind": "text", "text": "hello"}})
    ) == [FIRST_ANSWER_TOKEN]
    assert (
        analyzer.feed(
            packet(
                {
                    "type": "item_update",
                    "item": {"kind": "text", "purpose": "answer", "text": "hello"},
                }
            )
        )
        == []
    )
    analyzer.feed(packet({"type": "stop"}))
    assert analyzer.summary.answer_chars == 5
    assert analyzer.summary.reserved_assistant_message_id == 4321
    assert analyzer.completed_ok()


def test_reclassified_commentary_and_child_answers_do_not_count_as_answer() -> None:
    analyzer = ChatStreamAnalyzer()
    analyzer.feed(
        packet(
            {
                "type": "item_update",
                "item": {"kind": "text", "purpose": "answer", "text": "Preview"},
            }
        )
    )
    analyzer.feed(
        packet(
            {
                "type": "item_update",
                "item": {"kind": "text", "purpose": "commentary", "text": "Preview"},
            }
        )
    )
    analyzer.feed(
        packet(
            {
                "type": "item_update",
                "item": {"kind": "text", "purpose": "answer", "text": "Child"},
            },
            part="child-answer",
            parent="root",
        )
    )
    analyzer.feed(packet({"type": "stop"}))
    assert analyzer.summary.answer_chars == 0
    assert not analyzer.completed_ok()


def test_search_and_research_milestones_use_typed_metadata() -> None:
    analyzer = ChatStreamAnalyzer()
    analyzer.feed(
        packet(
            {"type": "item_update", "item": {"kind": "tool", "name": "research_agent"}},
            "research",
        )
    )
    analyzer.feed(
        packet(
            {
                "type": "item_update",
                "item": {"kind": "text", "purpose": "plan", "text": "Plan"},
            },
            "plan",
        )
    )
    analyzer.feed(
        packet(
            {
                "type": "item_update",
                "item": {"kind": "tool", "name": "web_search", "metadata": None},
            },
            "search",
        )
    )
    metadata: _Metadata = {
        "type": "search_result",
        "search_docs": [{"document_id": "one"}],
        "displayed_docs": None,
    }
    assert analyzer.feed(
        packet(
            {
                "type": "item_delta",
                "delta": {"kind": "tool_output", "metadata": metadata},
            },
            "search",
        )
    ) == [FIRST_SEARCH_DOC]
    analyzer.feed(
        packet(
            {
                "type": "item_update",
                "item": {"kind": "tool", "name": "web_search", "metadata": metadata},
            },
            "search",
        )
    )
    assert analyzer.summary.search_doc_count == 1
    assert {
        FIRST_DR_PLAN,
        FIRST_RESEARCH_AGENT,
        FIRST_SEARCH_DOC,
    } <= analyzer.summary.milestones_hit


def test_error_and_truncated_stream_fail() -> None:
    analyzer = ChatStreamAnalyzer()
    analyzer.feed(
        packet(
            {
                "type": "item_update",
                "item": {"kind": "text", "purpose": "answer", "text": "Partial"},
            }
        )
    )
    assert "truncated" in analyzer.failure_reason()
    analyzer.feed(json.dumps({"error": "boom"}))
    assert not analyzer.completed_ok()
    assert analyzer.failure_reason() == "boom"


def test_heartbeat_and_cancelled_run() -> None:
    analyzer = ChatStreamAnalyzer()
    analyzer.feed(packet({"type": "chat_heartbeat"}))
    analyzer.feed(packet({"type": "run_update", "status": "cancelled"}))
    analyzer.feed(packet({"type": "stop"}))
    assert analyzer.summary.heartbeats == 1
    assert analyzer.failure_reason() == "run cancelled"
    assert not analyzer.completed_ok()
