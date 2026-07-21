"""Unit tests for the shared search/paginate turn state."""

import threading
from typing import Any
from unittest.mock import MagicMock

from onyx.tools.tool_implementations.search.turn_state import SearchEntry
from onyx.tools.tool_implementations.search.turn_state import SearchToolTurnState


def _make_entry() -> SearchEntry:
    return SearchEntry(
        query_specs=[],
        merged_sections=[],
        cached_chunk_ids=set(),
        per_query_fetch_depth=50,
        user_query="test",
        effective_filters=None,
        acl_filters=None,
        embedding_model=MagicMock(),
        project_id_filter=None,
        persona_id_filter=None,
        bypass_acl=False,
    )


def test_ids_increment_from_one() -> None:
    state = SearchToolTurnState()
    first = state.register(_make_entry())
    second = state.register(_make_entry())

    assert first == 1
    assert second == 2
    assert state.get(1) is not None
    assert state.get(2) is not None
    assert state.get(3) is None


def test_concurrent_registration_yields_unique_ids() -> None:
    state = SearchToolTurnState()
    ids: list[int] = []
    lock = threading.Lock()

    def register() -> None:
        search_query_id = state.register(_make_entry())
        with lock:
            ids.append(search_query_id)

    threads = [threading.Thread(target=register) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(ids) == list(range(1, 21))


def test_rephrase_computed_once_across_parallel_callers() -> None:
    state = SearchToolTurnState()
    call_count = 0
    barrier = threading.Barrier(5)
    results: list[Any] = []
    results_lock = threading.Lock()

    def compute() -> str:
        nonlocal call_count
        call_count += 1
        return "rephrased"

    def caller() -> None:
        barrier.wait()
        result = state.get_or_compute_rephrase(compute)
        with results_lock:
            results.append(result)

    threads = [threading.Thread(target=caller) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert call_count == 1
    assert results == ["rephrased"] * 5


def test_rephrase_failure_is_cached_as_none() -> None:
    state = SearchToolTurnState()
    call_count = 0

    def failing_compute() -> str:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("LLM unavailable")

    assert state.get_or_compute_rephrase(failing_compute) is None
    # Not retried on subsequent calls.
    assert state.get_or_compute_rephrase(failing_compute) is None
    assert call_count == 1
