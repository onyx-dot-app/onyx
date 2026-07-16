"""Unit tests for generic_doc_sync's guard covering the SharePoint
drive-item-id → unique-ID-GUID Document.id transition."""

from collections.abc import Generator
from unittest.mock import MagicMock

from ee.onyx.external_permissions.utils import generic_doc_sync
from onyx.access.models import DocExternalAccess
from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import SlimDocument
from tests.utils.sharepoint import make_drive_item_id

_GUID = "2ab3c4d5-6e7f-4a1b-9c0d-1e2f3a4b5c6d"
_LEGACY_ID = make_drive_item_id(_GUID)
_ACCESS = ExternalAccess(
    external_user_emails={"user@acme.com"},
    external_user_group_ids=set(),
    is_public=False,
)


class _FakeSlimConnector:
    def __init__(self, slim_docs: list[SlimDocument]) -> None:
        self._slim_docs = slim_docs

    def retrieve_all_slim_docs_perm_sync(
        self, **_kwargs: object
    ) -> Generator[list[SlimDocument], None, None]:
        yield self._slim_docs


def _make_cc_pair() -> MagicMock:
    cc_pair = MagicMock()
    cc_pair.id = 1
    cc_pair.connector.indexing_start = None
    return cc_pair


def _run_doc_sync(
    slim_docs: list[SlimDocument],
    existing_doc_ids: list[str],
    doc_source: DocumentSource = DocumentSource.SHAREPOINT,
) -> list[DocExternalAccess]:
    results = generic_doc_sync(
        cc_pair=_make_cc_pair(),
        fetch_all_existing_docs_ids_fn=lambda: existing_doc_ids,
        callback=None,
        doc_source=doc_source,
        slim_connector=_FakeSlimConnector(slim_docs),  # ty: ignore[invalid-argument-type]
        label="test",
    )
    return [r for r in results if isinstance(r, DocExternalAccess)]


def test_legacy_id_not_revoked_while_fetched_under_guid() -> None:
    """A doc still indexed under its legacy drive-item id is fetched under its
    GUID id, so it looks "missing" — access must not be revoked."""
    yielded = _run_doc_sync(
        slim_docs=[SlimDocument(id=_GUID, external_access=_ACCESS)],
        existing_doc_ids=[_LEGACY_ID],
    )
    revoked = [r.doc_id for r in yielded if r.external_access == ExternalAccess.empty()]
    assert revoked == []
    assert [r.doc_id for r in yielded] == [_GUID]


def test_truly_missing_legacy_id_still_revoked() -> None:
    """A legacy-id doc whose GUID was NOT fetched is genuinely gone from the
    source — normal revocation applies."""
    other_guid = "0efe1b85-688f-4cbe-b9b7-1b8215f3a796"
    yielded = _run_doc_sync(
        slim_docs=[SlimDocument(id=other_guid, external_access=_ACCESS)],
        existing_doc_ids=[_LEGACY_ID],
    )
    revoked = [r.doc_id for r in yielded if r.external_access == ExternalAccess.empty()]
    assert revoked == [_LEGACY_ID]


def test_guard_only_applies_to_sharepoint() -> None:
    """Other sources keep the plain missing-doc revocation even if an id
    happens to decode as a drive-item id."""
    yielded = _run_doc_sync(
        slim_docs=[SlimDocument(id=_GUID, external_access=_ACCESS)],
        existing_doc_ids=[_LEGACY_ID],
        doc_source=DocumentSource.GOOGLE_DRIVE,
    )
    revoked = [r.doc_id for r in yielded if r.external_access == ExternalAccess.empty()]
    assert revoked == [_LEGACY_ID]
