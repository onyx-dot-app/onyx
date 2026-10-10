"""A censoring-only source such as Salesforce checks access at query time, so
its perm-synced documents get the public ACL at retrieval. Documents the same
source indexes under only a private or public connector keep their own ACL,
and a source with a doc sync never gets the public ACL this way."""

from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.access.access import _get_access_for_documents
from onyx.access.models import DocumentAccess
from onyx.configs.constants import DocumentSource
from onyx.db.enums import AccessType

_MODULE = "ee.onyx.access.access"
_DOC_ID = "doc"


def _document() -> MagicMock:
    document = MagicMock()
    document.id = _DOC_ID
    document.is_public = False
    document.external_user_emails = None
    document.external_user_group_ids = None
    return document


def _private_access() -> DocumentAccess:
    return DocumentAccess.build(
        user_emails=["owner@example.com"],
        user_groups=[],
        external_user_emails=[],
        external_user_group_ids=[],
        is_public=False,
    )


def _access_for(source: DocumentSource, access_types: set[AccessType]) -> bool:
    with (
        patch(
            f"{_MODULE}.get_access_for_documents_without_groups",
            return_value={_DOC_ID: _private_access()},
        ),
        patch(f"{_MODULE}.fetch_user_groups_for_documents", return_value=[]),
        patch(f"{_MODULE}.get_documents_by_ids", return_value=[_document()]),
        patch(f"{_MODULE}.get_document_sources", return_value={_DOC_ID: source}),
        patch(
            f"{_MODULE}.get_document_access_types",
            return_value={_DOC_ID: access_types},
        ),
        patch(f"{_MODULE}.fetch_public_external_group_ids", return_value=[]),
    ):
        return _get_access_for_documents([_DOC_ID], MagicMock())[_DOC_ID].is_public


@pytest.mark.parametrize(
    "access_types,expected_public",
    [
        ({AccessType.SYNC}, True),
        ({AccessType.SYNC_RESTRICTED}, True),
        ({AccessType.PRIVATE}, False),
        ({AccessType.PUBLIC}, False),
        (set(), False),
    ],
)
def test_censoring_only_source_is_open_only_when_perm_synced(
    access_types: set[AccessType], expected_public: bool
) -> None:
    assert _access_for(DocumentSource.SALESFORCE, access_types) is expected_public


def test_doc_synced_source_keeps_its_acl() -> None:
    assert _access_for(DocumentSource.GOOGLE_DRIVE, {AccessType.SYNC}) is False
