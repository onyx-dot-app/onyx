"""Guards for the tabular re-chunk migration's pass bookkeeping.

A failed re-chunk commits the smaller chunk_count before it fails, so the
oversized scan cannot find its own failures a second time. The next pass has to
take them by id, and the migration must not report completion while any are
still outstanding.
"""

from onyx.background.celery.tasks.tabular_rechunk.tasks import (
    _MAX_RETRY_PASSES,
    TabularRechunkProgress,
    _start_next_pass,
)


def test_a_clean_pass_completes_the_migration() -> None:
    progress = TabularRechunkProgress(cursor="doc-9", documents_indexed=12)
    _start_next_pass(progress)
    assert progress.completed
    assert progress.retrying_document_ids == []


def test_failures_are_queued_by_id_for_the_next_pass() -> None:
    progress = TabularRechunkProgress(
        cursor="doc-9", failed_document_ids=["doc-2", "doc-5"]
    )
    _start_next_pass(progress)

    assert not progress.completed
    assert progress.retry_passes == 1
    # Taken by id, and the cursor restarts so the pass can walk them.
    assert progress.retrying_document_ids == ["doc-2", "doc-5"]
    assert progress.cursor is None
    # Cleared, so the retry pass records its own failures against an empty list.
    assert progress.failed_document_ids == []


def test_a_retry_pass_queues_only_what_it_failed() -> None:
    progress = TabularRechunkProgress(
        retrying_document_ids=["doc-2", "doc-5"],
        failed_document_ids=["doc-5"],
        retry_passes=1,
    )
    _start_next_pass(progress)

    assert progress.retrying_document_ids == ["doc-5"]
    assert progress.retry_passes == 2
    assert not progress.completed


def test_a_retry_pass_that_fixes_everything_completes() -> None:
    progress = TabularRechunkProgress(
        retrying_document_ids=["doc-2"], failed_document_ids=[], retry_passes=1
    )
    _start_next_pass(progress)

    assert progress.completed
    assert progress.retrying_document_ids == []


def test_the_retry_count_is_bounded() -> None:
    progress = TabularRechunkProgress(
        retrying_document_ids=["doc-2"],
        failed_document_ids=["doc-2"],
        retry_passes=_MAX_RETRY_PASSES,
    )
    _start_next_pass(progress)

    # Terminal, and the ids stay on the record for the error log to name.
    assert progress.completed
    assert progress.retrying_document_ids == []
    assert progress.failed_document_ids == ["doc-2"]
