import os
from datetime import datetime
from datetime import timezone
from typing import Any

from danswer.connectors.models import InputType
from danswer.db.enums import AccessType
from danswer.server.documents.models import DocumentSource
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.document_search import (
    DocumentSearchManager,
)
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestCCPair
from tests.integration.common_utils.test_models import DATestConnector
from tests.integration.common_utils.test_models import DATestCredential
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.vespa import vespa_fixture
from tests.integration.connector_job_tests.slack.slack_api_utils import SlackManager


# @pytest.mark.xfail(reason="flaky - see DAN-789 for example", strict=False)
def test_slack_permission_sync(
    reset: None,
    vespa_client: vespa_fixture,
    slack_test_setup: tuple[dict[str, Any], dict[str, Any]],
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
            "workspace": "onyx-test-workspace",
            "channels": [public_channel["name"], private_channel["name"]],
        },
        is_public=True,
        groups=[],
        user_performing_action=admin_user,
    )
    cc_pair: DATestCCPair = CCPairManager.create(
        credential_id=credential.id,
        connector_id=connector.id,
        access_type=AccessType.SYNC,
        user_performing_action=admin_user,
    )
    CCPairManager.wait_for_indexing(
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
    SlackManager.add_message_to_channel(
        slack_client=slack_client,
        channel=public_channel,
        message=public_message,
    )
    SlackManager.add_message_to_channel(
        slack_client=slack_client,
        channel=private_channel,
        message=private_message,
    )

    # Run indexing
    before = datetime.now(timezone.utc)
    CCPairManager.run_once(cc_pair, admin_user)
    CCPairManager.wait_for_indexing(
        cc_pair=cc_pair,
        after=before,
        user_performing_action=admin_user,
    )

    # Run permission sync
    before = datetime.now(timezone.utc)
    CCPairManager.sync(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )
    CCPairManager.wait_for_sync(
        cc_pair=cc_pair,
        after=before,
        user_performing_action=admin_user,
    )

    # Search as admin with access to both channels
    danswer_doc_message_strings = DocumentSearchManager.search_documents(
        query="favorite number",
        user_performing_action=admin_user,
    )

    # Ensure admin user can see messages from both channels
    assert public_message in danswer_doc_message_strings
    assert private_message in danswer_doc_message_strings

    # Search as test_user_2 with access to only the public channel
    danswer_doc_message_strings = DocumentSearchManager.search_documents(
        query="favorite number",
        user_performing_action=test_user_2,
    )
    print(
        "\ntop_documents content before removing from private channel for test_user_2: ",
        danswer_doc_message_strings,
    )

    # Ensure test_user_2 can only see messages from the public channel
    assert public_message in danswer_doc_message_strings
    assert private_message not in danswer_doc_message_strings

    # Search as test_user_1 with access to both channels
    danswer_doc_message_strings = DocumentSearchManager.search_documents(
        query="favorite number",
        user_performing_action=test_user_1,
    )
    print(
        "\ntop_documents content before removing from private channel for test_user_1: ",
        danswer_doc_message_strings,
    )

    # Ensure test_user_1 can see messages from both channels
    assert public_message in danswer_doc_message_strings
    assert private_message in danswer_doc_message_strings

    # ----------------------MAKE THE CHANGES--------------------------
    print("\nRemoving test_user_1 from the private channel")
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
        user_performing_action=admin_user,
    )

    # ----------------------------VERIFY THE CHANGES---------------------------
    # Ensure test_user_1 can no longer see messages from the private channel
    # Search as test_user_1 with access to only the public channel
    danswer_doc_message_strings = DocumentSearchManager.search_documents(
        query="favorite number",
        user_performing_action=test_user_1,
    )
    print(
        "\ntop_documents content after removing from private channel for test_user_1: ",
        danswer_doc_message_strings,
    )

    # Ensure test_user_1 can only see messages from the public channel
    assert public_message in danswer_doc_message_strings
    assert private_message not in danswer_doc_message_strings
