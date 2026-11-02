"""A withheld source is kept out of the default lane and cleared in its own.

Two properties matter and they are separate. The default lane must never
return the source, whatever happens to the lane that serves it; and that
lane must return nothing the provider did not clear.
"""

import sys
from collections.abc import Generator, Mapping, Sequence
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.sources import load_event_sources
from onyx.context.search.enrichment.models import EnrichmentContext
from onyx.context.search.enrichment.registry import (
    ChunkPermissionFilter,
    enrichment_source_types,
    get_enrichment_filter,
    register_enrichment_source,
    unregister_enrichment_source,
)
from onyx.context.search.models import ChunkIndexRequest, IndexFilters, InferenceChunk
from onyx.context.search.retrieval.search_runner import search_chunks

WITHHELD = DocumentSource.MOCK_CONNECTOR
ORDINARY = DocumentSource.WEB


def _chunk(document_id: str, source: DocumentSource) -> InferenceChunk:
    return InferenceChunk(
        chunk_id=0,
        blurb="",
        content="",
        source_links=None,
        image_file_id=None,
        section_continuation=False,
        document_id=document_id,
        source_type=source,
        semantic_identifier=document_id,
        title=None,
        boost=0,
        score=1.0,
        hidden=False,
        metadata={},
        match_highlights=[],
        doc_summary="",
        chunk_context="",
        updated_at=None,
    )


def _request(source_types: list[DocumentSource] | None = None) -> ChunkIndexRequest:
    return ChunkIndexRequest(
        query="what did we decide about pricing",
        filters=IndexFilters(access_control_list=["public"], source_type=source_types),
    )


def _replace_source(permission_filter: ChunkPermissionFilter) -> None:
    """Take the source over for one test, whoever holds it."""
    unregister_enrichment_source(WITHHELD)
    register_enrichment_source(WITHHELD, permission_filter)


@pytest.fixture(autouse=True)
def restore_the_real_source() -> Generator[None, None, None]:
    """Let the loader register first, then put back what we displace.

    A source registers once per process. Claiming it before the loader runs
    would make the real registration raise, and the loader would roll that
    whole connector back -- webhook route included -- for every later test
    in the process.
    """
    load_event_sources()
    displaced = get_enrichment_filter(WITHHELD)
    try:
        yield
    finally:
        unregister_enrichment_source(WITHHELD)
        if displaced is not None:
            register_enrichment_source(WITHHELD, displaced)


@pytest.fixture
def allowing() -> None:
    """A registered source whose provider clears everything."""

    def permit(
        user_email: str,  # noqa: ARG001
        chunks: Sequence[InferenceChunk],
        secrets: Mapping[str, str],  # noqa: ARG001
    ) -> list[InferenceChunk]:
        return list(chunks)

    _replace_source(permit)


def _run(
    request: ChunkIndexRequest,
    contexts: list[EnrichmentContext],
    returns: dict[DocumentSource | None, list[InferenceChunk]],
) -> tuple[list[InferenceChunk], list[ChunkIndexRequest]]:
    """Run the fan-out with the index stubbed, recording each lane's query."""
    seen: list[ChunkIndexRequest] = []

    def fake_search(
        query_request: ChunkIndexRequest,
        document_index: Any,  # noqa: ARG001
        db_session: Any = None,  # noqa: ARG001
        embedding_model: Any = None,  # noqa: ARG001
    ) -> list[InferenceChunk]:
        seen.append(query_request)
        sources = query_request.filters.source_type
        key = sources[0] if sources and len(sources) == 1 else None
        return returns.get(key, [])

    with patch(
        "onyx.context.search.retrieval.search_runner._embed_and_hybrid_search",
        side_effect=fake_search,
    ):
        chunks = search_chunks(
            query_request=request,
            user_id=None,
            document_index=MagicMock(),
            prefetched_federated_retrieval_infos=[],
            prefetched_enrichment_contexts=contexts,
        )
    return chunks, seen


def _context(source: DocumentSource = WITHHELD) -> EnrichmentContext:
    permission_filter = get_enrichment_filter(source)
    assert permission_filter is not None
    return EnrichmentContext(
        source=source,
        permission_filter=permission_filter,
        user_email="someone@example.com",
        secrets={},
    )


def test_the_default_lane_is_told_to_withhold_the_source(allowing: None) -> None:  # noqa: ARG001
    _, seen = _run(_request(), contexts=[], returns={})

    default_lane = [q for q in seen if q.filters.source_type is None]
    assert len(default_lane) == 1
    assert default_lane[0].filters.excluded_source_type == [WITHHELD]


def test_the_source_stays_withheld_when_its_own_lane_cannot_run(
    allowing: None,  # noqa: ARG001
) -> None:
    """No contexts: no provider was asked, so nothing of this source is
    returned, but the default lane is still told to exclude it."""
    chunks, seen = _run(
        _request(),
        contexts=[],
        returns={None: [_chunk("web-1", ORDINARY)]},
    )

    assert [chunk.document_id for chunk in chunks] == ["web-1"]
    assert all(q.filters.excluded_source_type == [WITHHELD] for q in seen)


def test_the_withheld_lane_searches_only_its_own_source(allowing: None) -> None:  # noqa: ARG001
    _run(
        _request(),
        contexts=[_context()],
        returns={WITHHELD: [_chunk("zoom-1", WITHHELD)]},
    )


def test_cleared_results_join_the_ordinary_ones(allowing: None) -> None:  # noqa: ARG001
    chunks, seen = _run(
        _request(),
        contexts=[_context()],
        returns={
            None: [_chunk("web-1", ORDINARY)],
            WITHHELD: [_chunk("zoom-1", WITHHELD)],
        },
    )

    assert sorted(chunk.document_id for chunk in chunks) == ["web-1", "zoom-1"]
    withheld_lane = [q for q in seen if q.filters.source_type == [WITHHELD]]
    assert len(withheld_lane) == 1
    # Its own lane must not exclude what it was built to retrieve.
    assert withheld_lane[0].filters.excluded_source_type is None
    # The user's access filters are kept, not replaced.
    assert withheld_lane[0].filters.access_control_list == ["public"]


def test_a_provider_that_refuses_removes_its_results(allowing: None) -> None:  # noqa: ARG001
    def refuse(
        user_email: str,  # noqa: ARG001
        chunks: Sequence[InferenceChunk],  # noqa: ARG001
        secrets: Mapping[str, str],  # noqa: ARG001
    ) -> list[InferenceChunk]:
        return []

    _replace_source(refuse)
    chunks, _ = _run(
        _request(),
        contexts=[_context()],
        returns={
            None: [_chunk("web-1", ORDINARY)],
            WITHHELD: [_chunk("zoom-1", WITHHELD)],
        },
    )

    assert [chunk.document_id for chunk in chunks] == ["web-1"]


def test_a_provider_that_breaks_returns_none_of_its_results(
    allowing: None,  # noqa: ARG001
) -> None:
    """Failing open would publish content nobody cleared."""

    def explode(
        user_email: str,  # noqa: ARG001
        chunks: Sequence[InferenceChunk],  # noqa: ARG001
        secrets: Mapping[str, str],  # noqa: ARG001
    ) -> list[InferenceChunk]:
        raise RuntimeError("the provider is down")

    _replace_source(explode)
    chunks, _ = _run(
        _request(),
        contexts=[_context()],
        returns={
            None: [_chunk("web-1", ORDINARY)],
            WITHHELD: [_chunk("zoom-1", WITHHELD)],
        },
    )

    assert [chunk.document_id for chunk in chunks] == ["web-1"]


def test_asking_only_for_the_withheld_source_skips_the_default_lane(
    allowing: None,  # noqa: ARG001
) -> None:
    """The default lane would return nothing for it, so running it is only
    an embedding nobody reads."""
    chunks, seen = _run(
        _request(source_types=[WITHHELD]),
        contexts=[_context()],
        returns={WITHHELD: [_chunk("zoom-1", WITHHELD)]},
    )

    assert [chunk.document_id for chunk in chunks] == ["zoom-1"]
    assert len(seen) == 1


def test_one_search_asks_the_provider_once_per_document() -> None:
    """A search expands into several queries, and each one runs the lane.
    Asking the provider again for a document it already answered about
    spends a rate limit on a question with a known answer."""
    asked: list[list[str]] = []

    def permit(
        user_email: str,  # noqa: ARG001
        chunks: Sequence[InferenceChunk],
        secrets: Mapping[str, str],  # noqa: ARG001
    ) -> list[InferenceChunk]:
        asked.append([chunk.document_id for chunk in chunks])
        return list(chunks)

    _replace_source(permit)
    context = _context()
    for query in ("what did we decide", "pricing decision", "q1 list price"):
        _run(
            _request().model_copy(update={"query": query}),
            contexts=[context],
            returns={WITHHELD: [_chunk("zoom-1", WITHHELD)]},
        )

    assert asked == [["zoom-1"]]


def test_a_document_the_provider_refused_is_not_asked_about_again() -> None:
    asked: list[list[str]] = []

    def refuse(
        user_email: str,  # noqa: ARG001
        chunks: Sequence[InferenceChunk],
        secrets: Mapping[str, str],  # noqa: ARG001
    ) -> list[InferenceChunk]:
        asked.append([chunk.document_id for chunk in chunks])
        return []

    _replace_source(refuse)
    context = _context()
    for _ in range(3):
        chunks, _seen = _run(
            _request(),
            contexts=[context],
            returns={WITHHELD: [_chunk("zoom-1", WITHHELD)]},
        )
        assert chunks == []

    assert asked == [["zoom-1"]]


def test_a_new_document_is_still_asked_about(allowing: None) -> None:  # noqa: ARG001
    """Remembering the answered ones must not withhold the rest."""
    asked: list[list[str]] = []

    def permit(
        user_email: str,  # noqa: ARG001
        chunks: Sequence[InferenceChunk],
        secrets: Mapping[str, str],  # noqa: ARG001
    ) -> list[InferenceChunk]:
        asked.append(sorted(chunk.document_id for chunk in chunks))
        return list(chunks)

    _replace_source(permit)
    context = _context()
    _run(
        _request(),
        contexts=[context],
        returns={WITHHELD: [_chunk("zoom-1", WITHHELD)]},
    )
    chunks, _seen = _run(
        _request(),
        contexts=[context],
        returns={WITHHELD: [_chunk("zoom-1", WITHHELD), _chunk("zoom-2", WITHHELD)]},
    )

    assert asked == [["zoom-1"], ["zoom-2"]]
    assert sorted(chunk.document_id for chunk in chunks) == ["zoom-1", "zoom-2"]


def test_a_provider_that_broke_is_not_asked_again_in_the_same_search() -> None:
    """A 429 is what usually breaks it, and retrying per query is what
    caused the 429."""
    calls = 0

    def explode(
        user_email: str,  # noqa: ARG001
        chunks: Sequence[InferenceChunk],  # noqa: ARG001
        secrets: Mapping[str, str],  # noqa: ARG001
    ) -> list[InferenceChunk]:
        nonlocal calls
        calls += 1
        raise RuntimeError("rate limited")

    _replace_source(explode)
    context = _context()
    for _ in range(4):
        chunks, _seen = _run(
            _request(),
            contexts=[context],
            returns={
                None: [_chunk("web-1", ORDINARY)],
                WITHHELD: [_chunk("zoom-1", WITHHELD)],
            },
        )
        assert [chunk.document_id for chunk in chunks] == ["web-1"]

    assert calls == 1


def test_lanes_running_at_once_ask_once_between_them() -> None:
    """The lanes of one search share the context across threads."""
    import threading

    calls: list[int] = []
    gate = threading.Barrier(2, timeout=5)

    def slow_permit(
        user_email: str,  # noqa: ARG001
        chunks: Sequence[InferenceChunk],
        secrets: Mapping[str, str],  # noqa: ARG001
    ) -> list[InferenceChunk]:
        calls.append(1)
        return list(chunks)

    _replace_source(slow_permit)
    context = _context()

    def run_one() -> None:
        gate.wait()
        _run(
            _request(),
            contexts=[context],
            returns={WITHHELD: [_chunk("zoom-1", WITHHELD)]},
        )

    threads = [threading.Thread(target=run_one) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Both may ask if they race, but never more than once each, and the
    # second search in the same context must not ask at all.
    assert len(calls) <= 2
    before = len(calls)
    _run(
        _request(),
        contexts=[context],
        returns={WITHHELD: [_chunk("zoom-1", WITHHELD)]},
    )
    assert len(calls) == before


def test_a_source_stays_withheld_when_its_implementation_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loader swallows a failed import so one broken source cannot stop
    the server. A registry emptied that way must not un-withhold documents an
    earlier run already indexed, and an Onyx without the package installed
    must not serve them either. The static floor is what holds then."""
    unregister_enrichment_source(WITHHELD)
    monkeypatch.setattr(
        "onyx.context.search.enrichment.registry.WITHHELD_FROM_DEFAULT_SEARCH",
        frozenset({WITHHELD}),
    )

    assert WITHHELD in enrichment_source_types()

    _, seen = _run(_request(), contexts=[], returns={})

    assert all(query.filters.excluded_source_type == [WITHHELD] for query in seen)


def test_no_lane_is_resolved_for_a_source_with_no_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The floor withholds it; only a registered filter can serve it."""
    unregister_enrichment_source(WITHHELD)
    monkeypatch.setattr(
        "onyx.context.search.enrichment.registry.WITHHELD_FROM_DEFAULT_SEARCH",
        frozenset({WITHHELD}),
    )

    assert WITHHELD in enrichment_source_types()
    assert get_enrichment_filter(WITHHELD) is None


def test_a_source_in_the_floor_still_rolls_back_a_failed_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The floor is not a registration. A source listed there is already
    "withheld" before its module runs, so a rollback that diffed the
    withheld set would miss the handler a failed import left behind."""
    from onyx.connectors.event_inbox import sources as sources_module
    from onyx.connectors.event_inbox.handlers import get_event_handler

    monkeypatch.setattr(
        "onyx.context.search.enrichment.registry.WITHHELD_FROM_DEFAULT_SEARCH",
        frozenset({WITHHELD}),
    )
    unregister_enrichment_source(WITHHELD)
    half = "tests.unit.onyx.context.search.half_registering_withheld_source"
    monkeypatch.setattr(sources_module, "_loaded", False)
    monkeypatch.setattr(sources_module, "EVENT_SOURCE_MODULES", (half,))
    try:
        sources_module.load_event_sources()

        assert get_event_handler(WITHHELD) is None
        assert get_enrichment_filter(WITHHELD) is None
    finally:
        sys.modules.pop(half, None)
