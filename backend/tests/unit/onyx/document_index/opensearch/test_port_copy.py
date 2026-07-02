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
        present_tokenizer=MagicMock(),
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
        present_tokenizer=MagicMock(),
        surviving_doc_ids=lambda: set(),  # everything deleted
    )

    assert written == 0
    assert aborted is False
    future_index.index_raw_chunks.assert_not_called()


@patch("onyx.document_index.opensearch.port_copy._PORT_WRITE_PAGE_SIZE", 2)
@patch("onyx.document_index.opensearch.port_copy.re_embed_chunks")
def test_copier_rechecks_survival_before_each_sub_page(mock_reembed: MagicMock) -> None:
    """Survival is re-checked before EACH sub-page write, not once per page: a doc whose
    chunks span several sub-pages and is deleted between writes must not have its later
    sub-pages create-only resurrected into FUTURE."""
    present_client = MagicMock()
    # one page of 4 doc_a chunks -> 2 sub-pages at the patched _PORT_WRITE_PAGE_SIZE=2
    present_client.iter_chunks_for_doc_ids.return_value = [
        [_chunk("doc_a"), _chunk("doc_a"), _chunk("doc_a"), _chunk("doc_a")]
    ]
    mock_reembed.side_effect = _passthrough_reembed
    future_index = MagicMock()
    # survives the first sub-page's check, deleted before the second
    surviving = MagicMock(side_effect=[{"doc_a"}, set()])

    written, aborted = copy_present_chunks_to_future(
        present_client=present_client,
        future_index=future_index,
        doc_ids=["doc_a"],
        strategy=ReembedStrategy.MODEL_ONLY,
        embedder=MagicMock(),
        present_tokenizer=MagicMock(),
        surviving_doc_ids=surviving,
    )

    assert aborted is False
    assert written == 2  # only the first sub-page; the second dropped post-deletion
    future_index.index_raw_chunks.assert_called_once()
    assert surviving.call_count == 2  # re-checked per sub-page, not once for the page


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

    # should_abort is polled three times per page (loop-top heartbeat, post-re-embed,
    # and before the sub-page write): allow all of page 1's polls, then cancel at
    # page 2's loop-top poll.
    aborts = iter([False, False, False, True])

    written, aborted = copy_present_chunks_to_future(
        present_client=present_client,
        future_index=future_index,
        doc_ids=["doc_a", "doc_b"],
        strategy=ReembedStrategy.MODEL_ONLY,
        embedder=MagicMock(),
        present_tokenizer=MagicMock(),
        should_abort=lambda: next(aborts),
    )

    # only the first page was written; the second is skipped by the abort.
    assert written == 1
    assert aborted is True
    future_index.index_raw_chunks.assert_called_once()
    (written_chunks,), _ = future_index.index_raw_chunks.call_args
    assert [c.document_id for c in written_chunks] == ["doc_a"]


def _aug_ctx(rag_on: bool) -> MagicMock:
    ctx = MagicMock()
    ctx.future_enable_contextual_rag = rag_on
    return ctx


@patch("onyx.document_index.opensearch.port_copy.re_embed_chunks")
def test_rag_on_augmentation_reembeds_one_page_per_document(
    mock_reembed: MagicMock,
) -> None:
    # RAG-on AUGMENTATION re-embeds one doc per page (bounds the unheartbeated LLM
    # phase); a doc's chunks can span PIT pages, so they're reassembled first.
    present_client = MagicMock()
    present_client.iter_chunks_for_doc_ids.return_value = [
        [_chunk("doc_a"), _chunk("doc_b")],
        [_chunk("doc_a")],  # doc_a's chunks span two PIT pages
    ]
    future_index = MagicMock()

    events: list[tuple] = []

    def _reembed(page: list, *_: object, **__: object) -> list:
        events.append(("reembed", sorted({c.document_id for c in page})))
        return list(page)

    def _should_abort() -> bool:
        events.append(("heartbeat",))
        return False

    mock_reembed.side_effect = _reembed

    written, aborted = copy_present_chunks_to_future(
        present_client=present_client,
        future_index=future_index,
        doc_ids=["doc_a", "doc_b"],
        strategy=ReembedStrategy.AUGMENTATION,
        embedder=MagicMock(),
        present_tokenizer=MagicMock(),
        augmentation_ctx=_aug_ctx(rag_on=True),
        should_abort=_should_abort,
    )

    assert written == 3
    assert aborted is False

    # One re_embed per document (not per batch), each with all the doc's chunks.
    reembed_calls = [e for e in events if e[0] == "reembed"]
    assert [e[1] for e in reembed_calls] == [["doc_a"], ["doc_b"]]

    # A heartbeat precedes each re_embed, bracketing the slow phase.
    for i, e in enumerate(events):
        if e[0] == "reembed":
            assert events[i - 1] == ("heartbeat",)


@patch("onyx.document_index.opensearch.port_copy.re_embed_chunks")
def test_rag_off_augmentation_streams_per_pit_page(mock_reembed: MagicMock) -> None:
    # RAG-off AUGMENTATION has no LLM step, so it streams PIT pages as-is rather than
    # paying the per-document buffering cost.
    present_client = MagicMock()
    present_client.iter_chunks_for_doc_ids.return_value = [
        [_chunk("doc_a"), _chunk("doc_b")],
        [_chunk("doc_a")],  # doc_a spans PIT pages; not reassembled when RAG is off
    ]
    mock_reembed.side_effect = _passthrough_reembed
    future_index = MagicMock()

    written, aborted = copy_present_chunks_to_future(
        present_client=present_client,
        future_index=future_index,
        doc_ids=["doc_a", "doc_b"],
        strategy=ReembedStrategy.AUGMENTATION,
        embedder=MagicMock(),
        present_tokenizer=MagicMock(),
        augmentation_ctx=_aug_ctx(rag_on=False),
    )

    assert written == 3
    assert aborted is False
    # Streamed one re_embed per PIT page (not reassembled per document).
    reembed_pages = [call.args[0] for call in mock_reembed.call_args_list]
    doc_sets = [sorted({c.document_id for c in page}) for page in reembed_pages]
    assert doc_sets == [["doc_a", "doc_b"], ["doc_a"]]


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
        present_tokenizer=MagicMock(),
    )

    assert written == 2
    assert aborted is False
    future_index.index_raw_chunks.assert_called_once()
