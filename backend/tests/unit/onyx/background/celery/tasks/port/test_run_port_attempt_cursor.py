"""Unit coverage for the reindex-port producer's cursor-advance invariant.

`run_port_attempt` must only advance `last_processed_doc_id` past a batch that
was FULLY ported. When a batch aborts mid-copy (the copier returns aborted=True,
e.g. the stall watchdog marked the attempt FAILED while it was re-embedding), the
cursor must stay put — otherwise a FAILED-attempt resume scans `WHERE id > cursor`
and permanently skips the un-ported tail (silent corpus drop after the swap).
"""

from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.background.celery.tasks.port import tasks as port_tasks
from onyx.db.enums import PortAttemptStatus


@contextmanager
def _fake_session() -> Any:
    yield MagicMock()


def _make_attempt() -> MagicMock:
    attempt = MagicMock()
    attempt.status = PortAttemptStatus.IN_PROGRESS
    attempt.cancel_requested = False
    attempt.last_processed_doc_id = None
    attempt.up_to_doc_id = None
    attempt.docs_ported = 0
    attempt.cc_pair_id = 123
    attempt.search_settings_id = 2
    return attempt


def _patched(copy_result: tuple[int, bool], attempt: MagicMock) -> Any:
    """Patch every collaborator run_port_attempt touches so only the batch
    loop's cursor logic is under test. The copier is mocked to return
    `copy_result` directly (so _should_abort is never really invoked)."""
    copier = MagicMock()
    copier.copy_doc_batch.return_value = copy_result

    cc_pair = MagicMock()
    cc_pair.status = port_tasks.ConnectorCredentialPairStatus.ACTIVE

    patches = {
        "get_session_with_current_tenant": MagicMock(side_effect=_fake_session),
        "get_port_attempt": MagicMock(return_value=attempt),
        "get_search_settings_by_id": MagicMock(
            return_value=MagicMock(port_backfill_source_id=None)
        ),
        "get_current_search_settings": MagicMock(return_value=MagicMock()),
        "mark_port_in_progress": MagicMock(return_value=True),
        "PortCopier": MagicMock(return_value=copier),
        "get_connector_credential_pair_from_id": MagicMock(return_value=cc_pair),
        "get_document_ids_for_cc_pair_batch": MagicMock(
            side_effect=[["d1", "d2", "d3"], []]  # one batch, then exhausted
        ),
        "commit_port_cursor": MagicMock(),
        "mark_port_succeeded": MagicMock(),
        "mark_port_failed": MagicMock(),
        "mark_port_canceled": MagicMock(),
    }
    return patches


def test_cursor_not_advanced_when_batch_aborts() -> None:
    # Watchdog FAILs the attempt mid-copy: copier reports aborted=True and the row
    # flips terminal, so the next iteration stops.
    attempt = _make_attempt()
    patches = _patched((1, True), attempt)

    def _abort_flips_status(*_: Any, **__: Any) -> tuple[int, bool]:
        attempt.status = PortAttemptStatus.FAILED
        return (1, True)

    patches["PortCopier"].return_value.copy_doc_batch.side_effect = _abort_flips_status

    with patch.multiple(port_tasks, **patches):
        port_tasks.run_port_attempt(port_attempt_id=1)

    patches["commit_port_cursor"].assert_not_called()
    patches["mark_port_succeeded"].assert_not_called()


def test_cursor_advanced_when_batch_completes() -> None:
    # Positive control: a fully-ported batch advances the cursor to its last id.
    attempt = _make_attempt()
    patches = _patched((5, False), attempt)

    with patch.multiple(port_tasks, **patches):
        port_tasks.run_port_attempt(port_attempt_id=1)

    patches["commit_port_cursor"].assert_called_once()
    _, kwargs = patches["commit_port_cursor"].call_args
    assert kwargs["last_processed_doc_id"] == "d3"
    assert kwargs["docs_ported"] == 3
    patches["mark_port_succeeded"].assert_called_once()
