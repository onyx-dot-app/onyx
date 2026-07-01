"""Unit coverage for the reindex-port copier's mid-batch deletion guard.

`copy_present_chunks_to_future` re-checks document existence right before the
create-only write (after the slow re-embed) so a doc deleted while the batch was
being read/embedded is not resurrected into the FUTURE index.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.document_index.opensearch.port_copy import copy_present_chunks_to_future
from onyx.indexing.port_reembed import ReembedStrategy


def _chunk(doc_id: str) -> MagicMock:
    chunk = MagicMock()
    chunk.document_id = doc_id
    return chunk


def _passthrough_reembed(page: list, *_: object, **__: object) -> list:
    # re-embed stub: return the page unchanged (preserves document_ids).
    return list(page)


@patch("onyx.document_index.opensearch.port_copy.re_embed_chunks")
def test_copier_drops_docs_deleted_mid_batch(mock_reembed: MagicMock) -> None:
    present_client = MagicMock()
    present_client.iter_chunks_for_doc_ids.return_value = [
        [_chunk("doc_a"), _chunk("doc_b")]
    ]
    mock_reembed.side_effect = _passthrough_reembed
    future_index = MagicMock()

    written, aborted = copy_present_chunks_to_future(
        present_client=present_client,
        future_index=future_index,
        doc_ids=["doc_a", "doc_b"],
        strategy=ReembedStrategy.MODEL_ONLY,
        embedder=MagicMock(),
        surviving_doc_ids=lambda: {"doc_a"},  # doc_b deleted mid-batch
    )

    assert written == 1
    assert aborted is False
    (written_chunks,), _ = future_index.index_raw_chunks.call_args
    assert [c.document_id for c in written_chunks] == ["doc_a"]


@patch("onyx.document_index.opensearch.port_copy.re_embed_chunks")
def test_copier_skips_write_when_whole_batch_deleted(mock_reembed: MagicMock) -> None:
    present_client = MagicMock()
    present_client.iter_chunks_for_doc_ids.return_value = [[_chunk("doc_a")]]
    mock_reembed.side_effect = _passthrough_reembed
    future_index = MagicMock()

    written, aborted = copy_present_chunks_to_future(
        present_client=present_client,
        future_index=future_index,
        doc_ids=["doc_a"],
        strategy=ReembedStrategy.MODEL_ONLY,
        embedder=MagicMock(),
        surviving_doc_ids=lambda: set(),  # everything deleted
    )

    assert written == 0
    assert aborted is False
    future_index.index_raw_chunks.assert_not_called()


@patch("onyx.document_index.opensearch.port_copy.re_embed_chunks")
def test_copier_aborts_write_when_cancelled_mid_batch(mock_reembed: MagicMock) -> None:
    # Two pages; the attempt is cancelled after the first page is written.
    present_client = MagicMock()
    present_client.iter_chunks_for_doc_ids.return_value = [
        [_chunk("doc_a")],
        [_chunk("doc_b")],
    ]
    mock_reembed.side_effect = _passthrough_reembed
    future_index = MagicMock()

    # should_abort is polled twice per page (pre-filter + before the sub-page
    # write): allow both of page 1's polls, then cancel at page 2's first poll.
    aborts = iter([False, False, True])

    written, aborted = copy_present_chunks_to_future(
        present_client=present_client,
        future_index=future_index,
        doc_ids=["doc_a", "doc_b"],
        strategy=ReembedStrategy.MODEL_ONLY,
        embedder=MagicMock(),
        should_abort=lambda: next(aborts),
    )

    # only the first page was written; the second is skipped by the abort.
    assert written == 1
    assert aborted is True
    future_index.index_raw_chunks.assert_called_once()
    (written_chunks,), _ = future_index.index_raw_chunks.call_args
    assert [c.document_id for c in written_chunks] == ["doc_a"]


@patch("onyx.document_index.opensearch.port_copy.re_embed_chunks")
def test_copier_writes_all_without_filter(mock_reembed: MagicMock) -> None:
    present_client = MagicMock()
    present_client.iter_chunks_for_doc_ids.return_value = [
        [_chunk("doc_a"), _chunk("doc_b")]
    ]
    mock_reembed.side_effect = _passthrough_reembed
    future_index = MagicMock()

    written, aborted = copy_present_chunks_to_future(
        present_client=present_client,
        future_index=future_index,
        doc_ids=["doc_a", "doc_b"],
        strategy=ReembedStrategy.MODEL_ONLY,
        embedder=MagicMock(),
    )

    assert written == 2
    assert aborted is False
    future_index.index_raw_chunks.assert_called_once()
