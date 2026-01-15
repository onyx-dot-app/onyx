from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from ee.onyx.external_permissions.jira.doc_sync import jira_doc_sync
from onyx.access.models import DocExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.utils import DocumentRow
from onyx.db.utils import SortOrder
from onyx.utils.variable_functionality import global_version


# In order to get these tests to run, use the credentials from Bitwarden.
# Search up "ENV vars for local and Github tests", and find the Jira relevant key-value pairs.
# Required env vars: JIRA_USER_EMAIL, JIRA_API_TOKEN


class DocExternalAccessSet(BaseModel):
    """A version of DocExternalAccess that uses sets for comparison."""

    doc_id: str
    external_user_emails: set[str]
    external_user_group_ids: set[str]
    is_public: bool

    @classmethod
    def from_doc_external_access(
        cls, doc_external_access: DocExternalAccess
    ) -> "DocExternalAccessSet":
        return cls(
            doc_id=doc_external_access.doc_id,
            external_user_emails=doc_external_access.external_access.external_user_emails,
            external_user_group_ids=doc_external_access.external_access.external_user_group_ids,
            is_public=doc_external_access.external_access.is_public,
        )


def test_jira_doc_sync(
    db_session: Session,
    jira_connector_config: dict[str, Any],
    jira_credential_json: dict[str, Any],
) -> None:
    """Test that Jira doc sync returns documents with correct permissions.

    This test uses the AS project which has applicationRole permission,
    meaning all documents should be marked as public.
    """
    # NOTE: must set EE on or else the connector will skip the perm syncing
    global_version.set_ee()

    try:
        # Use AS project specifically for this test
        connector_config = {
            **jira_connector_config,
            "project_key": "AS",  # DailyConnectorTestProject
        }

        connector = Connector(
            name="Test Jira Doc Sync Connector",
            source=DocumentSource.JIRA,
            input_type=InputType.POLL,
            connector_specific_config=connector_config,
            refresh_freq=None,
            prune_freq=None,
            indexing_start=None,
        )
        db_session.add(connector)
        db_session.flush()

        credential = Credential(
            source=DocumentSource.JIRA,
            credential_json=jira_credential_json,
        )
        db_session.add(credential)
        db_session.flush()

        cc_pair = ConnectorCredentialPair(
            connector_id=connector.id,
            credential_id=credential.id,
            name="Test Jira Doc Sync CC Pair",
            status=ConnectorCredentialPairStatus.ACTIVE,
            access_type=AccessType.SYNC,
            auto_sync_options=None,
        )
        db_session.add(cc_pair)
        db_session.flush()
        db_session.refresh(cc_pair)

        # Mock functions - we don't have existing docs in the test DB
        def fetch_all_existing_docs_fn(
            sort_order: SortOrder | None = None,
        ) -> list[DocumentRow]:
            return []

        def fetch_all_existing_docs_ids_fn() -> list[str]:
            return []

        doc_sync_iter = jira_doc_sync(
            cc_pair=cc_pair,
            fetch_all_existing_docs_fn=fetch_all_existing_docs_fn,
            fetch_all_existing_docs_ids_fn=fetch_all_existing_docs_ids_fn,
        )

        # Expected documents from the danswerai.atlassian.net Jira instance
        # The AS project has applicationRole permission, so all docs should be public
        _EXPECTED_JIRA_DOCS = [
            DocExternalAccessSet(
                doc_id="https://danswerai.atlassian.net/browse/AS-3",
                external_user_emails=set(),
                external_user_group_ids=set(),
                is_public=True,
            ),
            DocExternalAccessSet(
                doc_id="https://danswerai.atlassian.net/browse/AS-4",
                external_user_emails=set(),
                external_user_group_ids=set(),
                is_public=True,
            ),
        ]

        expected_docs = {doc.doc_id: doc for doc in _EXPECTED_JIRA_DOCS}
        actual_docs = {
            doc.doc_id: DocExternalAccessSet.from_doc_external_access(doc)
            for doc in doc_sync_iter
        }
        assert expected_docs == actual_docs, (
            f"Expected docs: {expected_docs}\n" f"Actual docs: {actual_docs}"
        )
    finally:
        db_session.rollback()


def test_jira_doc_sync_with_specific_permissions(
    db_session: Session,
    jira_connector_config: dict[str, Any],
    jira_credential_json: dict[str, Any],
) -> None:
    """Test that Jira doc sync returns documents with specific permissions.

    This test uses a project that has specific user permissions to verify
    that specific users are correctly extracted.
    """
    # NOTE: must set EE on or else the connector will skip the perm syncing
    global_version.set_ee()

    try:
        # Use SUP project which has specific user permissions
        connector_config = {
            **jira_connector_config,
            "project_key": "SUP",
        }

        connector = Connector(
            name="Test Jira Doc Sync with Groups Connector",
            source=DocumentSource.JIRA,
            input_type=InputType.POLL,
            connector_specific_config=connector_config,
            refresh_freq=None,
            prune_freq=None,
            indexing_start=None,
        )
        db_session.add(connector)
        db_session.flush()

        credential = Credential(
            source=DocumentSource.JIRA,
            credential_json=jira_credential_json,
        )
        db_session.add(credential)
        db_session.flush()

        cc_pair = ConnectorCredentialPair(
            connector_id=connector.id,
            credential_id=credential.id,
            name="Test Jira Doc Sync with Groups CC Pair",
            status=ConnectorCredentialPairStatus.ACTIVE,
            access_type=AccessType.SYNC,
            auto_sync_options=None,
        )
        db_session.add(cc_pair)
        db_session.flush()
        db_session.refresh(cc_pair)

        # Mock functions
        def fetch_all_existing_docs_fn(
            sort_order: SortOrder | None = None,
        ) -> list[DocumentRow]:
            return []

        def fetch_all_existing_docs_ids_fn() -> list[str]:
            return []

        doc_sync_iter = jira_doc_sync(
            cc_pair=cc_pair,
            fetch_all_existing_docs_fn=fetch_all_existing_docs_fn,
            fetch_all_existing_docs_ids_fn=fetch_all_existing_docs_ids_fn,
        )

        docs = list(doc_sync_iter)

        # SUP project should have user-specific permissions (not public)
        assert len(docs) > 0, "Expected at least one document from SUP project"

        _EXPECTED_USER_EMAILS = set(
            ["yuhong@onyx.app", "chris@onyx.app", "founders@onyx.app"]
        )
        _EXPECTED_USER_GROUP_IDS = set(["jira-users-danswerai"])

        for doc in docs:
            assert doc.doc_id.startswith("https://danswerai.atlassian.net/browse/SUP-")
            # SUP project has specific users assigned, not applicationRole
            assert (
                not doc.external_access.is_public
            ), f"Document {doc.doc_id} should not be public"
            # Should have user emails
            assert doc.external_access.external_user_emails == _EXPECTED_USER_EMAILS
            assert (
                doc.external_access.external_user_group_ids == _EXPECTED_USER_GROUP_IDS
            )
    finally:
        db_session.rollback()
