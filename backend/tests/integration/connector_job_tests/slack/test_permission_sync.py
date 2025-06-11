import os
from datetime import datetime
from datetime import timezone

import pytest

from onyx.connectors.models import InputType
from onyx.connectors.slack.models import ChannelType
from onyx.db.enums import AccessType
from onyx.server.documents.models import DocumentSource
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.document_search import (
    DocumentSearchManager,
)
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestCCPair
from tests.integration.common_utils.test_models import DATestConnector
from tests.integration.common_utils.test_models import DATestCredential
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.vespa import vespa_fixture
from tests.integration.connector_job_tests.slack.slack_api_utils import SlackManager


# NOTE(rkuo): it isn't yet clear if the reason these were previously xfail'd
# still exists. May need to xfail again if flaky (DAN-789)
@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Permission tests are enterprise only",
)
def test_slack_permission_sync(
    reset: None,
    vespa_client: vespa_fixture,
    slack_test_setup: tuple[ChannelType, ChannelType],
) -> None:
    public_channel, private_channel = slack_test_setup

    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(
        email="admin@onyx-test.com",
    )

    # Creating a non-admin user
    test_user_1: DATestUser = UserManager.create(
        email="test_user_1@onyx-test.com",
    )

    # Creating a non-admin user
    test_user_2: DATestUser = UserManager.create(
        email="test_user_2@onyx-test.com",
    )

    slack_client = SlackManager.get_slack_client(os.environ["SLACK_BOT_TOKEN"])
    email_id_map = SlackManager.build_slack_user_email_id_map(slack_client)
    admin_user_id = email_id_map[admin_user.email]

    LLMProviderManager.create(user_performing_action=admin_user)

    before = datetime.now(timezone.utc)
    credential: DATestCredential = CredentialManager.create(
        source=DocumentSource.SLACK,
        credential_json={
            "slack_bot_token": os.environ["SLACK_BOT_TOKEN"],
        },
        user_performing_action=admin_user,
    )
    connector: DATestConnector = ConnectorManager.create(
        name="Slack",
        input_type=InputType.POLL,
        source=DocumentSource.SLACK,
        connector_specific_config={
            "channels": [public_channel["name"], private_channel["name"]],
        },
        access_type=AccessType.SYNC,
        groups=[],
        user_performing_action=admin_user,
    )
    cc_pair: DATestCCPair = CCPairManager.create(
        credential_id=credential.id,
        connector_id=connector.id,
        access_type=AccessType.SYNC,
        user_performing_action=admin_user,
    )
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair,
        after=before,
        user_performing_action=admin_user,
    )

    # Add test_user_1 and admin_user to the private channel
    desired_channel_members = [admin_user, test_user_1]
    SlackManager.set_channel_members(
        slack_client=slack_client,
        admin_user_id=admin_user_id,
        channel=private_channel,
        user_ids=[email_id_map[user.email] for user in desired_channel_members],
    )

    public_message = "Steve's favorite number is 809752"
    private_message = "Sara's favorite number is 346794"

    # Add messages to channels
    print(f"\n Adding public message to channel: {public_message}")
    SlackManager.add_message_to_channel(
        slack_client=slack_client,
        channel=public_channel,
        message=public_message,
    )
    print(f"\n Adding private message to channel: {private_message}")
    SlackManager.add_message_to_channel(
        slack_client=slack_client,
        channel=private_channel,
        message=private_message,
    )

    # Run indexing
    before = datetime.now(timezone.utc)
    CCPairManager.run_once(
        cc_pair, from_beginning=True, user_performing_action=admin_user
    )
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair,
        after=before,
        user_performing_action=admin_user,
    )

    # Run permission sync
    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )
    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        number_of_updated_docs=2,
        user_performing_action=admin_user,
    )

    # Search as admin with access to both channels
    print("\nSearching as admin user")
    onyx_doc_message_strings = DocumentSearchManager.search_documents(
        query="favorite number",
        user_performing_action=admin_user,
    )
    print(
        "\n documents retrieved by admin user: ",
        onyx_doc_message_strings,
    )

    # Ensure admin user can see messages from both channels
    assert public_message in onyx_doc_message_strings
    assert private_message in onyx_doc_message_strings

    # Search as test_user_2 with access to only the public channel
    print("\n Searching as test_user_2")
    onyx_doc_message_strings = DocumentSearchManager.search_documents(
        query="favorite number",
        user_performing_action=test_user_2,
    )
    print(
        "\n documents retrieved by test_user_2: ",
        onyx_doc_message_strings,
    )

    # Ensure test_user_2 can only see messages from the public channel
    assert public_message in onyx_doc_message_strings
    assert private_message not in onyx_doc_message_strings

    # Search as test_user_1 with access to both channels
    print("\n Searching as test_user_1")
    onyx_doc_message_strings = DocumentSearchManager.search_documents(
        query="favorite number",
        user_performing_action=test_user_1,
    )
    print(
        "\n documents retrieved by test_user_1 before being removed from private channel: ",
        onyx_doc_message_strings,
    )

    # Ensure test_user_1 can see messages from both channels
    assert public_message in onyx_doc_message_strings
    assert private_message in onyx_doc_message_strings

    # ----------------------MAKE THE CHANGES--------------------------
    print("\n Removing test_user_1 from the private channel")
    before = datetime.now(timezone.utc)
    # Remove test_user_1 from the private channel
    desired_channel_members = [admin_user]
    SlackManager.set_channel_members(
        slack_client=slack_client,
        admin_user_id=admin_user_id,
        channel=private_channel,
        user_ids=[email_id_map[user.email] for user in desired_channel_members],
    )

    # Run permission sync
    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )
    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        number_of_updated_docs=1,
        user_performing_action=admin_user,
    )

    # ----------------------------VERIFY THE CHANGES---------------------------
    # Ensure test_user_1 can no longer see messages from the private channel
    # Search as test_user_1 with access to only the public channel

    onyx_doc_message_strings = DocumentSearchManager.search_documents(
        query="favorite number",
        user_performing_action=test_user_1,
    )
    print(
        "\n documents retrieved by test_user_1 after being removed from private channel: ",
        onyx_doc_message_strings,
    )

    # Ensure test_user_1 can only see messages from the public channel
    assert public_message in onyx_doc_message_strings
    assert private_message not in onyx_doc_message_strings


# NOTE(rkuo): it isn't yet clear if the reason these were previously xfail'd
# still exists. May need to xfail again if flaky (DAN-789)
@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Permission tests are enterprise only",
)
def test_slack_group_permission_sync(
    reset: None,
    vespa_client: vespa_fixture,
    slack_test_setup: tuple[ChannelType, ChannelType],
) -> None:
    """
    This test ensures that permission sync overrides onyx group access.
    """
    public_channel, private_channel = slack_test_setup

    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(
        email="admin@onyx-test.com",
    )

    # Creating a non-admin user
    test_user_1: DATestUser = UserManager.create(
        email="test_user_1@onyx-test.com",
    )

    # Create a user group and adding the non-admin user to it
    user_group = UserGroupManager.create(
        name="test_group",
        user_ids=[test_user_1.id],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync(
        user_groups_to_check=[user_group],
        user_performing_action=admin_user,
    )

    slack_client = SlackManager.get_slack_client(os.environ["SLACK_BOT_TOKEN"])
    email_id_map = SlackManager.build_slack_user_email_id_map(slack_client)
    admin_user_id = email_id_map[admin_user.email]

    LLMProviderManager.create(user_performing_action=admin_user)

    # Add only admin to the private channel
    SlackManager.set_channel_members(
        slack_client=slack_client,
        admin_user_id=admin_user_id,
        channel=private_channel,
        user_ids=[admin_user_id],
    )

    before = datetime.now(timezone.utc)
    credential = CredentialManager.create(
        source=DocumentSource.SLACK,
        credential_json={
            "slack_bot_token": os.environ["SLACK_BOT_TOKEN"],
        },
        user_performing_action=admin_user,
    )

    # Create connector with sync access and assign it to the user group
    connector = ConnectorManager.create(
        name="Slack",
        input_type=InputType.POLL,
        source=DocumentSource.SLACK,
        connector_specific_config={
            "channels": [private_channel["name"]],
        },
        access_type=AccessType.SYNC,
        groups=[user_group.id],
        user_performing_action=admin_user,
    )

    cc_pair = CCPairManager.create(
        credential_id=credential.id,
        connector_id=connector.id,
        access_type=AccessType.SYNC,
        user_performing_action=admin_user,
        groups=[user_group.id],
    )

    # Add a test message to the private channel
    private_message = "This is a secret message: 987654"
    SlackManager.add_message_to_channel(
        slack_client=slack_client,
        channel=private_channel,
        message=private_message,
    )

    # Run indexing
    CCPairManager.run_once(
        cc_pair, from_beginning=True, user_performing_action=admin_user
    )
    CCPairManager.wait_for_indexing_completion(
        cc_pair=cc_pair,
        after=before,
        user_performing_action=admin_user,
    )

    # Run permission sync
    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )
    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        number_of_updated_docs=1,
        user_performing_action=admin_user,
    )

    # Verify admin can see the message
    admin_docs = DocumentSearchManager.search_documents(
        query="secret message",
        user_performing_action=admin_user,
    )
    assert private_message in admin_docs

    # Verify test_user_1 cannot see the message despite being in the group
    # (Slack permissions should take precedence)
    user_1_docs = DocumentSearchManager.search_documents(
        query="secret message",
        user_performing_action=test_user_1,
    )
    assert private_message not in user_1_docs
