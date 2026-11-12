"""A code mode response that ends with open cells saves what they did, live and on reload."""

import threading
import time
from collections.abc import Sequence
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.context.search.models import SearchDocsResponse
from onyx.llm.model_response import (
    Delta,
)
from onyx.server.query_and_chat.chat_backend import get_chat_session
from onyx.server.query_and_chat.streaming_models import (
    CitationInfo,
    OverallStop,
    Packet,
    SearchToolDocumentsDelta,
    StreamingError,
)
from onyx.tools.tool_implementations.code_mode.models import (
    CellWindow,
)
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from tests.external_dependency_unit.answer.stream_test_utils import (
    create_chat_session,
    final_answer,
)
from tests.external_dependency_unit.code_mode_helpers import (
    ChatLLM,
    assert_cells_released,
    closing_deltas,
    code_mode_shape,
    saved_cells,
    send,
    tool_step,
    tool_text,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.mock_search_provider import (
    MockWebProvider,
    MockWebSearchResult,
    use_mock_web_provider,
)

pytestmark = pytest.mark.usefixtures("full_deployment_setup", "mock_external_deps")


def _wait(event: threading.Event) -> None:
    assert event.wait(30)


def _stop_reasons(packets: Sequence[object]) -> list[str | None]:
    return [
        packet.obj.stop_reason
        for packet in packets
        if isinstance(packet, Packet) and isinstance(packet.obj, OverallStop)
    ]


def _citation_numbers(window: CellWindow) -> set[int]:
    return {
        number
        for call in window.calls
        if isinstance(call.details, SearchDocsResponse)
        for number in call.details.citation_mapping
    }


@pytest.mark.usefixtures("default_llm_provider")
def test_turn_deadline_closes_open_cells_and_reports_its_own_stop_reason(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    user = make_test_user("code_mode_deadline")
    session = create_chat_session(db_session, user)
    program = "import asyncio\nprint('started')\nawait asyncio.sleep(600)\n"
    # The model waits on the cell, then never answers.
    llm = ChatLLM(
        [
            tool_step(
                "execute_code", "start", {"code": program, "yield_time_ms": 1000}
            ),
            tool_step("wait_code", "wait", {"cell_id": 1, "yield_time_ms": 1000}),
        ],
        hold_open=True,
    )
    started = time.monotonic()
    with patch("onyx.chat.execution.CHAT_EXECUTION_TIMEOUT_S", 10):
        parts = send(session.id, user, llm, "Run until stopped.")
    assert time.monotonic() - started < 30
    assert not [part for part in parts if isinstance(part, StreamingError)]
    assert _stop_reasons(parts) == ["timed_out"]
    assert len(closing_deltas(parts)) == 1
    assert_cells_released()

    saved = saved_cells(db_session, session.id)
    assert [(d.observation, d.status) for d in saved] == [
        (0, "running"),
        (1, "running"),
    ]
    closing = saved[1].closing
    assert closing is not None and closing.reason == "response_ended"

    chat_detail = get_chat_session(
        session_id=session.id, user=user, db_session=db_session
    )
    [replayed] = chat_detail.packets
    assert _stop_reasons(replayed) == ["timed_out"]
    assert len(closing_deltas(replayed)) == 1
    assert code_mode_shape(replayed) == code_mode_shape(parts)


@pytest.mark.usefixtures("default_llm_provider")
def test_closing_searches_get_their_own_citations_and_reach_later_turns(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    user = make_test_user("code_mode_closing_search")
    session = create_chat_session(db_session, user)
    program = (
        "await web_search(queries=['alpha topic'])\n"
        "print('first')\n"
        "yield_control()\n"
        "await web_search(queries=['beta topic'])\n"
        "print('second')\n"
        "await web_search(queries=['latch'])\n"
    )
    latch_started, latch_release = threading.Event(), threading.Event()
    # The answer starts after the second search ended, so only the closing reports it.
    llm = ChatLLM(
        [
            tool_step("execute_code", "start", {"code": program}),
            Delta(content="Started."),
        ],
        gates={1: lambda: _wait(latch_started)},
        hold_open=True,
    )
    with use_mock_web_provider(db_session) as web:
        assert isinstance(web, MockWebProvider)
        search = web.search

        def latched(query: str) -> Sequence[WebSearchResult]:
            # The third search runs until the response ends.
            if query == "latch":
                latch_started.set()
                latch_release.wait(30)
            return search(query)

        for topic in ("alpha", "beta"):
            web.add_results(
                f"{topic} topic",
                [
                    MockWebSearchResult(
                        title=f"{topic} page",
                        link=f"https://example.com/{topic}",
                        snippet=f"About {topic}.",
                    )
                ],
            )
        try:
            with patch.object(web, "search", side_effect=latched):
                parts = send(session.id, user, llm, "Search twice.")
        finally:
            latch_release.set()
    assert final_answer(parts) == "Started."
    assert_cells_released()

    [saved] = saved_cells(db_session, session.id)
    assert saved.status == "running"
    closing = saved.closing
    assert closing is not None
    assert [call.state for call in closing.calls] == ["ok", "unfinished"]
    observed = _citation_numbers(saved)
    closed = _citation_numbers(closing)
    assert observed and closed and not observed & closed

    def links(packets: Sequence[object]) -> list[str | None]:
        return [
            doc.link
            for packet in packets
            if isinstance(packet, Packet)
            and isinstance(packet.obj, SearchToolDocumentsDelta)
            for doc in packet.obj.documents
        ]

    assert links(parts) == ["https://example.com/alpha", "https://example.com/beta"]
    chat_detail = get_chat_session(
        session_id=session.id, user=user, db_session=db_session
    )
    [replayed] = chat_detail.packets
    assert links(replayed) == links(parts)

    [number] = closed
    follow_up = ChatLLM([Delta(content=f"Beta is covered [{number}].")])
    second = send(session.id, user, follow_up, "What did the second search find?")
    assert final_answer(second).startswith("Beta is covered")
    citations = [
        packet.obj
        for packet in second
        if isinstance(packet, Packet) and isinstance(packet.obj, CitationInfo)
    ]
    assert [citation.citation_number for citation in citations] == [number]
    assert "web_search: ok" in tool_text(follow_up.requests[0]["prompt"], "start")
