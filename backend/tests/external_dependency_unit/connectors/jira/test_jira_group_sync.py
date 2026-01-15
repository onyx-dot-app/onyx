from typing import Any

from sqlalchemy.orm import Session

from ee.onyx.external_permissions.jira.group_sync import jira_group_sync
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from shared_configs.contextvars import get_current_tenant_id
from tests.daily.connectors.confluence.models import ExternalUserGroupSet


# In order to get these tests to run, use the credentials from Bitwarden.
# Search up "ENV vars for local and Github tests", and find the Jira relevant key-value pairs.
# Required env vars: JIRA_USER_EMAIL, JIRA_API_TOKEN

# Expected groups from the danswerai.atlassian.net Jira instance
# Note: These groups are shared with Confluence since they're both Atlassian products
# App accounts (bots, integrations) are filtered out
_EXPECTED_JIRA_GROUPS = [
    ExternalUserGroupSet(
        id="Yuhong Only No Chris Allowed",
        user_emails={"yuhong@onyx.app"},
        gives_anyone_access=False,
    ),
    ExternalUserGroupSet(
        id="confluence-admins-danswerai",
        user_emails={"chris@onyx.app", "yuhong@onyx.app"},
        gives_anyone_access=False,
    ),
    ExternalUserGroupSet(
        id="confluence-user-access-admins-danswerai",
        user_emails={"hagen@danswer.ai"},
        gives_anyone_access=False,
    ),
    ExternalUserGroupSet(
        id="confluence-users-danswerai",
        user_emails={
            "chris@onyx.app",
            "founders@onyx.app",
            "hagen@danswer.ai",
            "pablo@onyx.app",
            "yuhong@onyx.app",
        },
        gives_anyone_access=False,
    ),
    ExternalUserGroupSet(
        id="jira-admins-danswerai",
        user_emails={"founders@onyx.app", "hagen@danswer.ai", "pablo@onyx.app"},
        gives_anyone_access=False,
    ),
    ExternalUserGroupSet(
        id="jira-user-access-admins-danswerai",
        user_emails={"hagen@danswer.ai"},
        gives_anyone_access=False,
    ),
    ExternalUserGroupSet(
        id="jira-users-danswerai",
        user_emails={
            "chris@onyx.app",
            "founders@onyx.app",
            "hagen@danswer.ai",
            "pablo@onyx.app",
        },
        gives_anyone_access=False,
    ),
    ExternalUserGroupSet(
        id="org-admins",
        user_emails={
            "chris@onyx.app",
            "founders@onyx.app",
            "yuhong@onyx.app",
        },
        gives_anyone_access=False,
    ),
]


def test_jira_group_sync(
    db_session: Session,
    jira_connector_config: dict[str, Any],
    jira_credential_json: dict[str, Any],
) -> None:
    try:
        connector = Connector(
            name="Test Jira Connector",
            source=DocumentSource.JIRA,
            input_type=InputType.POLL,
            connector_specific_config=jira_connector_config,
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
            name="Test Jira CC Pair",
            status=ConnectorCredentialPairStatus.ACTIVE,
            access_type=AccessType.SYNC,
            auto_sync_options=None,
        )
        db_session.add(cc_pair)
        db_session.flush()
        db_session.refresh(cc_pair)

        tenant_id = get_current_tenant_id()
        group_sync_iter = jira_group_sync(
            tenant_id=tenant_id,
            cc_pair=cc_pair,
        )

        expected_groups = {group.id: group for group in _EXPECTED_JIRA_GROUPS}
        actual_groups = {
            group.id: ExternalUserGroupSet.from_model(external_user_group=group)
            for group in group_sync_iter
        }
        assert expected_groups == actual_groups
    finally:
        db_session.rollback()
