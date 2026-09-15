from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ee.onyx.external_permissions.jira.doc_sync import jira_doc_sync
from onyx.access.models import DocExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.models import InputType, SlimDocument
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import Connector, ConnectorCredentialPair, Credential
from onyx.db.utils import DocumentRow, SortOrder
from tests.external_dependency_unit.connectors.jira.conftest import JiraTestCredentials
from tests.utils.secret_names import TestSecret

JIRA_BASE_URL = "https://danswerai.atlassian.net"
TEAM_MANAGED_PROJECT_KEY = "TP"
TEAM_MANAGED_USER_EMAIL = "hagen@danswer.ai"
TEAM_MANAGED_GROUP_ID = "org-admins"

pytestmark = [
    pytest.mark.usefixtures("enable_ee"),
    pytest.mark.secrets(TestSecret.JIRA_USER_EMAIL, TestSecret.JIRA_API_TOKEN),
]


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


def _sync_project_permissions(
    db_session: Session,
    jira_connector_config: dict[str, Any],
    jira_credentials: JiraTestCredentials,
    project_key: str,
) -> list[DocExternalAccessSet]:
    try:
        connector = Connector(
            name=f"Test Jira {project_key} Doc Sync Connector",
            source=DocumentSource.JIRA,
            input_type=InputType.POLL,
            connector_specific_config={
                **jira_connector_config,
                "project_key": project_key,
            },
            refresh_freq=None,
            prune_freq=None,
            indexing_start=None,
        )
        db_session.add(connector)
        db_session.flush()

        credential = Credential(
            source=DocumentSource.JIRA,
            credential_json=jira_credentials.as_credential_json(),
        )
        db_session.add(credential)
        db_session.flush()
        db_session.expire(credential)

        cc_pair = ConnectorCredentialPair(
            connector_id=connector.id,
            credential_id=credential.id,
            name=f"Test Jira {project_key} Doc Sync CC Pair",
            status=ConnectorCredentialPairStatus.ACTIVE,
            access_type=AccessType.SYNC,
            auto_sync_options=None,
        )
        db_session.add(cc_pair)
        db_session.flush()
        db_session.refresh(cc_pair)

        def fetch_all_existing_docs_fn(
            sort_order: SortOrder | None = None,  # noqa: ARG001
        ) -> list[DocumentRow]:
            return []

        def fetch_all_existing_docs_ids_fn() -> list[str]:
            return []

        return [
            DocExternalAccessSet.from_doc_external_access(doc)
            for doc in jira_doc_sync(
                cc_pair=cc_pair,
                fetch_all_existing_docs_fn=fetch_all_existing_docs_fn,
                fetch_all_existing_docs_ids_fn=fetch_all_existing_docs_ids_fn,
            )
            if isinstance(doc, DocExternalAccess)
        ]
    finally:
        db_session.rollback()


def test_jira_team_managed_project_doc_sync(
    jira_credentials: JiraTestCredentials,
) -> None:
    """A team-managed project maps its roles to a private document ACL."""
    connector = JiraConnector(
        jira_base_url=JIRA_BASE_URL,
        project_key=TEAM_MANAGED_PROJECT_KEY,
    )
    connector.load_credentials(jira_credentials.as_credential_json())

    documents = [
        item
        for batch in connector.retrieve_all_slim_docs_perm_sync()
        for item in batch
        if isinstance(item, SlimDocument)
    ]
    assert len(documents) == 1

    document = documents[0]
    assert document.id == f"{JIRA_BASE_URL}/browse/{TEAM_MANAGED_PROJECT_KEY}-2"
    assert document.external_access is not None
    assert document.external_access.external_user_emails == {TEAM_MANAGED_USER_EMAIL}
    assert document.external_access.external_user_group_ids == {TEAM_MANAGED_GROUP_ID}
    assert not document.external_access.is_public


def test_jira_doc_sync(
    db_session: Session,
    jira_connector_config: dict[str, Any],
    jira_credentials: JiraTestCredentials,
) -> None:
    expected_docs = {
        f"{JIRA_BASE_URL}/browse/AS-3": DocExternalAccessSet(
            doc_id=f"{JIRA_BASE_URL}/browse/AS-3",
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=True,
        ),
        f"{JIRA_BASE_URL}/browse/AS-4": DocExternalAccessSet(
            doc_id=f"{JIRA_BASE_URL}/browse/AS-4",
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=True,
        ),
    }
    actual_docs = {
        doc.doc_id: doc
        for doc in _sync_project_permissions(
            db_session=db_session,
            jira_connector_config=jira_connector_config,
            jira_credentials=jira_credentials,
            project_key="AS",
        )
    }
    assert actual_docs == expected_docs


def test_jira_doc_sync_with_specific_permissions(
    db_session: Session,
    jira_connector_config: dict[str, Any],
    jira_credentials: JiraTestCredentials,
) -> None:
    docs = _sync_project_permissions(
        db_session=db_session,
        jira_connector_config=jira_connector_config,
        jira_credentials=jira_credentials,
        project_key="SUP",
    )
    assert docs

    expected_user_emails = {
        "yuhong@onyx.app",
        "chris@onyx.app",
        "founders@onyx.app",
        "oauth@onyx.app",
    }
    for doc in docs:
        assert doc.doc_id.startswith(f"{JIRA_BASE_URL}/browse/SUP-")
        assert not doc.is_public
        assert doc.external_user_emails == expected_user_emails
        assert doc.external_user_group_ids == {"jira-users-danswerai"}
