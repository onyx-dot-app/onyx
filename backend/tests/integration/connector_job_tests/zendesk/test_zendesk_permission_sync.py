"""End-to-end Zendesk permission sync against the CI Zendesk account.

The account holds fixtures whose names start with `onyx_ps_`: agents with
different ticket access, end users, an organization that shares its tickets,
a public and a private group, user segments, restricted articles, and tickets
with and without an internal note. The test reads them and changes nothing in
Zendesk. It indexes one articles pair and one tickets pair with Sync with
Zendesk, runs doc sync and group sync, and checks which documents each Onyx
user can read through the stored ACLs. The expected access is what each
fixture user can open in Zendesk itself, checked by reading as that user.
"""

import os
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.models import InputType
from onyx.connectors.zendesk.source_operations import ZendeskSourceOperations
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType
from tests.integration.common_utils.document_acl import (
    get_all_connector_documents,
    get_user_document_access_via_acl,
)
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestCCPair, DATestUser
from tests.utils.secret_names import TestSecret

pytestmark = [
    pytest.mark.secrets(
        TestSecret.ZENDESK_SUBDOMAIN,
        TestSecret.ZENDESK_EMAIL,
        TestSecret.ZENDESK_TOKEN,
    ),
    pytest.mark.skipif(
        os.environ.get("RUN_EE_TESTS", "").lower() != "true",
        reason="Permission tests are enterprise only",
    ),
]

FIXTURE_PREFIX = "onyx_ps_"
# Fixture users of the CI account, by the part of their email after the prefix.
FIXTURE_USERS = [
    "agent_all",  # Team lead: reads all tickets, manages the Help Center
    "agent_groups",  # within-groups: member of the private group
    "agent_r_groups",  # within-groups: member of the public group
    "eu_vip",  # tag onyx_ps_vip, member of the sharing organization
    "eu_vip_no_org",  # tag onyx_ps_vip, no organization
    "eu_plain",  # no tags
    "eu_org_peer",  # member of the sharing organization
]

# Articles by title, tickets by subject, each with the fixture users who can
# open it in Zendesk.
EXPECTED_ARTICLE_READERS: dict[str, set[str]] = {
    # Segment: signed-in users tagged onyx_ps_vip in the organization.
    "onyx_ps_article vip and org": {"agent_all", "eu_vip"},
    # Segment: staff in the private group.
    "onyx_ps_article staff private": {"agent_all", "agent_groups"},
}
EXPECTED_TICKET_READERS: dict[str, set[str]] = {
    # Private group and the sharing organization, with an internal note: no
    # end user, though Zendesk shows the requester the public comments.
    "onyx_ps_ticket private group with note": {
        "agent_all",
        "agent_groups",
        "agent_r_groups",  # follower
    },
    # Public group, the sharing organization, an end-user CC, no internal note.
    "onyx_ps_ticket public group clean": {
        "agent_all",
        "agent_r_groups",
        "eu_vip",  # requester
        "eu_plain",  # CC
        "eu_org_peer",  # organization shares its tickets
    },
    # Private group, assigned to agent_groups, no internal note.
    "onyx_ps_ticket assigned private": {"agent_all", "agent_groups", "eu_plain"},
}


class ZendeskSyncEnv(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    admin_user: DATestUser
    users: dict[str, DATestUser]
    articles_pair: DATestCCPair
    tickets_pair: DATestCCPair
    # Onyx document id by fixture article title or ticket subject.
    doc_ids: dict[str, str]


def _credential_json(test_secrets: dict[TestSecret, str]) -> dict[str, Any]:
    return {
        "zendesk_subdomain": test_secrets[TestSecret.ZENDESK_SUBDOMAIN],
        "zendesk_email": test_secrets[TestSecret.ZENDESK_EMAIL],
        "zendesk_token": test_secrets[TestSecret.ZENDESK_TOKEN],
    }


def _fixture_doc_ids(credential_json: dict[str, Any]) -> dict[str, str]:
    """Finds the fixtures by name, so the test does not depend on their ids."""
    ops = ZendeskSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None, DocumentSource.ZENDESK.value, credential_json
        )
    )
    doc_ids: dict[str, str] = {}
    after_cursor: str | None = None
    while True:
        page = ops.get_article_page(start_time=0, after_cursor=after_cursor)
        for article in page.data:
            if article["title"] in EXPECTED_ARTICLE_READERS:
                doc_ids[article["title"]] = f"article:{article['id']}"
        if not page.has_more:
            break
        after_cursor = page.meta["after_cursor"]
    start_time: int | None = 0
    while True:
        ticket_page = ops.get_ticket_page(start_time=start_time)
        for ticket in ticket_page.data:
            if ticket.get("subject") in EXPECTED_TICKET_READERS:
                doc_ids[ticket["subject"]] = f"zendesk_ticket_{ticket['id']}"
        if not ticket_page.has_more:
            break
        start_time = ticket_page.meta["end_time"]
    missing = (set(EXPECTED_ARTICLE_READERS) | set(EXPECTED_TICKET_READERS)) - set(
        doc_ids
    )
    assert not missing, f"fixtures missing from the CI Zendesk account: {missing}"
    return doc_ids


def _pair(
    admin_user: DATestUser, credential_id: int, name: str, config: dict[str, Any]
) -> DATestCCPair:
    connector = ConnectorManager.create(
        name=name,
        input_type=InputType.POLL,
        source=DocumentSource.ZENDESK,
        connector_specific_config=config,
        access_type=AccessType.SYNC,
        user_performing_action=admin_user,
    )
    return CCPairManager.create(
        credential_id=credential_id,
        connector_id=connector.id,
        access_type=AccessType.SYNC,
        user_performing_action=admin_user,
    )


@pytest.fixture()
def zendesk_sync_env(
    reset: None,  # noqa: ARG001
    test_secrets: dict[TestSecret, str],
) -> Generator[ZendeskSyncEnv, None, None]:
    credential_json = _credential_json(test_secrets)
    doc_ids = _fixture_doc_ids(credential_json)
    try:
        # The first user created is the Onyx admin.
        admin_user = UserManager.create(email=f"{FIXTURE_PREFIX}onyx_admin@example.com")
        users = {
            name: UserManager.create(email=f"{FIXTURE_PREFIX}{name}@example.com")
            for name in FIXTURE_USERS
        }
        credential = CredentialManager.create(
            source=DocumentSource.ZENDESK,
            credential_json=credential_json,
            user_performing_action=admin_user,
        )
        yield ZendeskSyncEnv(
            admin_user=admin_user,
            users=users,
            articles_pair=_pair(
                admin_user,
                credential.id,
                "Zendesk Articles Permission Sync Test",
                {"content_type": "articles"},
            ),
            tickets_pair=_pair(
                admin_user,
                credential.id,
                "Zendesk Tickets Permission Sync Test",
                {"content_type": "tickets", "grant_end_users": True},
            ),
            doc_ids=doc_ids,
        )
    finally:
        reset_all()


def _index_and_sync(env: ZendeskSyncEnv, cc_pair: DATestCCPair) -> None:
    """Index once (wait out the run that starts when the pair is created),
    then run doc sync and group sync and wait for both. Indexing already sets
    each document's access, so the doc sync changes nothing in the search
    index, and the checks read the stored ACLs."""
    admin = env.admin_user
    CCPairManager.wait_for_indexing_inactive(
        cc_pair=cc_pair, user_performing_action=admin
    )
    before = datetime.now(timezone.utc)
    CCPairManager.run_once(cc_pair, from_beginning=True, user_performing_action=admin)
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair, after=before, user_performing_action=admin
    )
    # Zendesk is not changed, so any sync that starts after indexing will do.
    synced_after = datetime.now(timezone.utc)
    CCPairManager.sync(cc_pair=cc_pair, user_performing_action=admin)
    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=synced_after,
        user_performing_action=admin,
        should_wait_for_index_sync=False,
    )


def _readers(env: ZendeskSyncEnv, doc_id: str) -> set[str]:
    readers: set[str] = set()
    with get_session_with_current_tenant() as db_session:
        for name, user in env.users.items():
            if get_user_document_access_via_acl(
                test_user=user, document_ids=[doc_id], db_session=db_session
            ):
                readers.add(name)
    return readers


def _assert_readers(
    env: ZendeskSyncEnv, cc_pair: DATestCCPair, expected: dict[str, set[str]]
) -> None:
    with get_session_with_current_tenant() as db_session:
        indexed = set(get_all_connector_documents(cc_pair, db_session))
    for title, readers in expected.items():
        doc_id = env.doc_ids[title]
        assert doc_id in indexed, f"{title} ({doc_id}) was not indexed"
        assert _readers(env, doc_id) == readers, title


def test_zendesk_permission_sync(zendesk_sync_env: ZendeskSyncEnv) -> None:
    env = zendesk_sync_env

    _index_and_sync(env, env.articles_pair)
    _assert_readers(env, env.articles_pair, EXPECTED_ARTICLE_READERS)

    _index_and_sync(env, env.tickets_pair)
    _assert_readers(env, env.tickets_pair, EXPECTED_TICKET_READERS)
