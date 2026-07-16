"""Unit tests for the pruning guard covering the SharePoint drive-item-id →
unique-ID-GUID Document.id transition."""

from onyx.background.celery.tasks.pruning.tasks import (
    _drop_sharepoint_legacy_ids_awaiting_replacement,
)
from tests.utils.sharepoint import make_drive_item_id

_GUID = "2ab3c4d5-6e7f-4a1b-9c0d-1e2f3a4b5c6d"
_LEGACY_ID = make_drive_item_id(_GUID)


def test_legacy_id_protected_until_replacement_indexed() -> None:
    """The file still exists (its GUID was yielded) but the GUID doc isn't
    indexed yet — pruning the legacy doc would lose the only copy."""
    kept = _drop_sharepoint_legacy_ids_awaiting_replacement(
        [_LEGACY_ID],
        yielded_doc_ids={_GUID},
        indexed_doc_ids={_LEGACY_ID},
    )
    assert kept == []


def test_legacy_id_pruned_once_replacement_indexed() -> None:
    """Both the legacy doc and its GUID replacement are indexed — the legacy
    duplicate prunes normally."""
    kept = _drop_sharepoint_legacy_ids_awaiting_replacement(
        [_LEGACY_ID],
        yielded_doc_ids={_GUID},
        indexed_doc_ids={_LEGACY_ID, _GUID},
    )
    assert kept == [_LEGACY_ID]


def test_legacy_id_pruned_when_file_gone_from_source() -> None:
    """The file was deleted at the source (GUID not yielded) — normal prune."""
    kept = _drop_sharepoint_legacy_ids_awaiting_replacement(
        [_LEGACY_ID],
        yielded_doc_ids={"0efe1b85-688f-4cbe-b9b7-1b8215f3a796"},
        indexed_doc_ids={_LEGACY_ID},
    )
    assert kept == [_LEGACY_ID]


def test_non_legacy_ids_pass_through() -> None:
    """GUID ids and page ids never decode as drive-item ids — untouched."""
    ids = [_GUID, "some-other-id"]
    kept = _drop_sharepoint_legacy_ids_awaiting_replacement(
        ids,
        yielded_doc_ids=set(),
        indexed_doc_ids=set(ids),
    )
    assert kept == ids
