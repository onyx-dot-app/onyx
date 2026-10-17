"""Guards for the tabular re-chunk migration's pass bookkeeping.

A document the pass could not re-chunk keeps its old chunk count, so the next
pass finds it by rescanning. The migration must not report completion while
any are still outstanding, and must not rescan for ever either.
"""

from onyx.background.celery.tasks.tabular_rechunk.tasks import (
    _MAX_PASSES,
    TabularRechunkProgress,
    _finish_pass,
)


def test_a_clean_pass_completes_the_migration() -> None:
    progress = TabularRechunkProgress(cursor="doc-9", documents_indexed=12)
    _finish_pass(progress)
    assert progress.completed


def test_failures_send_the_scan_back_to_the_top() -> None:
    progress = TabularRechunkProgress(cursor="doc-9", failed_document_ids=["doc-2"])
    _finish_pass(progress)

    assert not progress.completed
    assert progress.cursor is None
    # Cleared, so the next pass is judged on its own failures.
    assert progress.failed_document_ids == []
    assert progress.passes == 1


def test_the_pass_count_is_bounded() -> None:
    progress = TabularRechunkProgress(
        failed_document_ids=["doc-2"], passes=_MAX_PASSES - 1
    )
    _finish_pass(progress)

    # Terminal, and the ids stay on the record for the error log to name.
    assert progress.completed
    assert progress.failed_document_ids == ["doc-2"]
