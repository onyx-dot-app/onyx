"""Prevent JSM attachment permission sync from creating unindexed DB rows."""

from unittest.mock import MagicMock

from ee.onyx.db.document import upsert_document_external_perms
from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource

_ACCESS = ExternalAccess(
    external_user_emails=set(),
    external_user_group_ids=set(),
    is_public=True,
)
_TICKET = "https://example.atlassian.net/browse/HELP-10"
_ATTACHMENT = f"{_TICKET}/attachment/123"


def test_missing_jsm_attachment_does_not_create_metadata_only_document() -> None:
    session = MagicMock()
    session.scalar.return_value = None

    created = upsert_document_external_perms(
        session, _ATTACHMENT, _ACCESS, DocumentSource.JIRA_SERVICE_MANAGEMENT
    )

    assert created is False
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_missing_jsm_ticket_retains_existing_upsert_behavior() -> None:
    session = MagicMock()
    session.scalar.return_value = None

    created = upsert_document_external_perms(
        session, _TICKET, _ACCESS, DocumentSource.JIRA_SERVICE_MANAGEMENT
    )

    assert created is True
    session.add.assert_called_once()
    session.commit.assert_called_once()


def test_plain_jira_missing_document_retains_existing_upsert_behavior() -> None:
    session = MagicMock()
    session.scalar.return_value = None

    created = upsert_document_external_perms(
        session, _ATTACHMENT, _ACCESS, DocumentSource.JIRA
    )

    assert created is True
    session.add.assert_called_once()
    session.commit.assert_called_once()


def test_existing_jsm_attachment_may_receive_updated_permissions() -> None:
    session = MagicMock()
    document = MagicMock()
    document.external_user_emails = []
    document.external_user_group_ids = []
    document.is_public = False
    session.scalar.return_value = document

    created = upsert_document_external_perms(
        session, _ATTACHMENT, _ACCESS, DocumentSource.JIRA_SERVICE_MANAGEMENT
    )

    assert created is False
    assert document.is_public is True
    session.add.assert_not_called()
    session.commit.assert_called_once()
