"""Unit tests for the pre-swap sample check on the port-flow swap gate.

Every other swap condition reads the port's own record of itself; this one reads
the destination index. These pin the decisions that make it safe to gate a swap
on: it holds the swap when sampled documents are absent, treats an unreachable
cluster as "not ready" rather than "ready", forgives a document deleted between
the sample and the lookup, and can be switched off entirely.
"""

from unittest.mock import MagicMock, patch

from onyx.db.swap_index import _ported_documents_present_in_new_index

_SCOPES = [(1, 2, "doc-zzz")]


def _search_settings() -> MagicMock:
    settings = MagicMock()
    settings.id = 42
    settings.index_name = "danswer_chunk_new"
    return settings


def _run(
    sampled: list[str],
    missing: list[str] | Exception,
    still_in_postgres: set[str] | None = None,
    sample_size: int = 100,
    opensearch_enabled: bool = True,
) -> bool:
    index = MagicMock()
    if isinstance(missing, Exception):
        index.get_documents_missing_chunks.side_effect = missing
    else:
        index.get_documents_missing_chunks.return_value = missing

    with (
        patch("onyx.db.swap_index.PORT_SWAP_VERIFY_SAMPLE_SIZE", sample_size),
        patch(
            "onyx.db.swap_index.ENABLE_OPENSEARCH_INDEXING_FOR_ONYX", opensearch_enabled
        ),
        patch("onyx.db.swap_index.sample_ported_document_ids", return_value=sampled),
        patch("onyx.db.swap_index.build_opensearch_document_index", return_value=index),
        patch(
            "onyx.db.swap_index.filter_existing_document_ids",
            return_value=(
                still_in_postgres
                if still_in_postgres is not None
                else set(missing if isinstance(missing, list) else [])
            ),
        ),
    ):
        return _ported_documents_present_in_new_index(
            MagicMock(), _search_settings(), _SCOPES
        )


def test_ready_when_every_sampled_document_is_present() -> None:
    assert _run(sampled=["doc-a", "doc-b"], missing=[]) is True


def test_holds_the_swap_when_a_sampled_document_is_absent() -> None:
    assert _run(sampled=["doc-a", "doc-b"], missing=["doc-b"]) is False


def test_document_deleted_after_sampling_is_not_treated_as_loss() -> None:
    # Absent from the index, and no longer in Postgres either -- legitimately gone.
    assert _run(sampled=["doc-a"], missing=["doc-a"], still_in_postgres=set()) is True


def test_partial_deletion_still_holds_on_the_survivor() -> None:
    assert (
        _run(
            sampled=["doc-a", "doc-b"],
            missing=["doc-a", "doc-b"],
            still_in_postgres={"doc-b"},
        )
        is False
    )


def test_unreachable_cluster_holds_the_swap() -> None:
    assert _run(sampled=["doc-a"], missing=ConnectionError("cluster down")) is False


def test_disabled_by_sample_size_zero() -> None:
    assert _run(sampled=["doc-a"], missing=["doc-a"], sample_size=0) is True


def test_skipped_when_opensearch_indexing_is_off() -> None:
    assert _run(sampled=["doc-a"], missing=["doc-a"], opensearch_enabled=False) is True


def test_nothing_to_sample_is_ready() -> None:
    assert _run(sampled=[], missing=[]) is True


def test_sample_is_seeded_per_search_settings() -> None:
    """A stable seed keeps the same documents under test across beat ticks; a fresh
    random draw would eventually pass against a partly-missing index."""
    index = MagicMock()
    index.get_documents_missing_chunks.return_value = []
    with (
        patch("onyx.db.swap_index.PORT_SWAP_VERIFY_SAMPLE_SIZE", 100),
        patch("onyx.db.swap_index.build_opensearch_document_index", return_value=index),
        patch(
            "onyx.db.swap_index.sample_ported_document_ids", return_value=["doc-a"]
        ) as sample_mock,
    ):
        _ported_documents_present_in_new_index(MagicMock(), _search_settings(), _SCOPES)
    _, kwargs = sample_mock.call_args
    assert kwargs["seed"] == "42"
    assert kwargs["limit"] == 100
