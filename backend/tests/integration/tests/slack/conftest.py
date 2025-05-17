import os
import shutil
import tempfile
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from time import sleep
from typing import Any

import pytest
from slack_sdk import WebClient

from onyx.db.enums import AccessType
from onyx.server.documents.models import DocumentSource
from onyx.utils.logger import setup_logger
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.file import FileManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.slack import SlackManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestCCPair
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import SlackTestContext
from tests.integration.common_utils.test_server_utils import fastapi_server_context
from tests.integration.tests.slack.utils import create_slack_bot
from tests.integration.tests.slack.utils import create_slack_channel_config
from tests.integration.tests.slack.utils import create_standard_answer_with_category

logger = setup_logger()


@pytest.fixture(scope="session")
def reset_db_and_index() -> None:
    """Fixture to reset the database and Vespa index before each test."""
    reset_all()
    logger.info("Database and Vespa index reset successfully.")


def _admin_user() -> DATestUser:
    """Creates the admin user once per module."""
    user = UserManager.create(email="admin@onyx-test.com")
    logger.info(f"Admin user created: {user.email}")
    return user


def _slack_bot(admin_user: DATestUser) -> dict[str, Any]:
    """Fixture to create a Slack bot and return its details."""

    app_token = os.environ.get("SLACK_APP_TOKEN")
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    if not app_token or not bot_token:
        raise RuntimeError(
            "SLACK_APP_TOKEN and/or SLACK_BOT_TOKEN environment variables not set"
        )

    # Create the Slack bot
    bot_details = create_slack_bot(
        bot_token=bot_token, app_token=app_token, user_performing_action=admin_user
    )
    logger.info(f"Slack bot created: {bot_details}")
    return bot_details


def _slack_bot_client() -> WebClient:
    """Fixture to create a Slack bot client."""
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("SLACK_BOT_TOKEN environment variable not set")
    slack_client = WebClient(token=bot_token)
    return slack_client


def _slack_user_client() -> WebClient:
    """Fixture to create a Slack user client."""
    user_token = os.environ.get("SLACK_USER_TOKEN")
    if not user_token:
        raise RuntimeError("SLACK_USER_TOKEN environment variable not set")
    slack_client = WebClient(token=user_token)
    return slack_client


def _slack_secondary_user_client() -> WebClient:
    """Fixture to create a secondary Slack user client."""
    user_token = os.environ.get("SLACK_SECONDARY_USER_TOKEN")
    if not user_token:
        raise RuntimeError("SLACK_SECONDARY_USER_TOKEN environment variable not set")
    slack_client = WebClient(token=user_token)
    return slack_client


def _create_standard_answer_and_category(
    admin_user: DATestUser,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Creates a standard answer category and a standard answer using the combined utility."""
    category, standard_answer = create_standard_answer_with_category(
        category_name="IT",
        keyword="support",
        answer="If you need any support, Please contact support@onyx.app",
        user_performing_action=admin_user,
    )
    logger.info(f"Standard answer category created: {category}")
    logger.info(f"Standard answer created: {standard_answer}")
    return category, standard_answer


def _create_slack_channels(
    slack_user_client: WebClient,
    slack_bot_client: WebClient,
    secondary_user_client: WebClient,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Creates Slack channels with the bot and user"""
    slack_bot_user_id, _ = SlackManager.get_client_user_and_bot_ids(slack_bot_client)
    secondary_user_id, _ = SlackManager.get_client_user_and_bot_ids(
        secondary_user_client
    )
    logger.info(f"Slack bot user ID: {slack_bot_user_id}")
    logger.info(f"Secondary user ID: {secondary_user_id}")
    slack_user_id, _ = SlackManager.get_client_user_and_bot_ids(slack_user_client)
    logger.info(f"Slack user ID: {slack_user_id}")
    # Create a channels
    test_channel_1 = SlackManager.create_slack_channel(
        slack_client=slack_user_client,
        channel_name="config-test-channel-1",
        is_private=True,
    )
    logger.info(f"Channel created: {test_channel_1}")

    test_channel_2 = SlackManager.create_slack_channel(
        slack_client=slack_user_client,
        channel_name="config-test-channel-2",
        is_private=True,
    )
    logger.info(f"Channel created: {test_channel_2}")

    # add the bot to the channels
    SlackManager.set_channel_members(
        slack_client=slack_user_client,
        admin_user_id=slack_user_id,
        channel=test_channel_1,
        user_ids=[slack_bot_user_id, secondary_user_id],
    )
    logger.info(f"Added bot to channel: {test_channel_1}")
    SlackManager.set_channel_members(
        slack_client=slack_user_client,
        admin_user_id=slack_user_id,
        channel=test_channel_2,
        user_ids=[slack_bot_user_id, secondary_user_id],
    )
    logger.info(f"Added bot to channel: {test_channel_2}")

    return test_channel_1, test_channel_2


def _create_slack_channel_config(
    channel_name: str,
    slack_bot_id: str,
    admin_user: DATestUser,
) -> dict[str, Any]:
    """Creates a Slack channel config."""
    slack_channel_config = create_slack_channel_config(
        bot_id=slack_bot_id,
        channel_name=channel_name,
        user_performing_action=admin_user,
    )
    logger.info(f"Slack channel config created: {slack_channel_config}")
    return slack_channel_config


def _create_file_connector(
    admin_user: DATestUser, file_name: str, access_type: AccessType = AccessType.PUBLIC
) -> DATestCCPair:
    """Creates a file connector."""
    # Upload a file to the connector
    filepath = f"tests/integration/tests/slack/resources/{file_name}"
    files = FileManager.upload_file_for_connector(
        file_path=filepath,
        file_name=file_name,
        user_performing_action=admin_user,
    )
    logger.info(f"Uploaded {len(files)} documents.")
    logger.info(f"Files: {files}")
    file_paths = files["file_paths"]
    logger.info(f"File paths: {file_paths}")
    connector_config = {"zip_metadata": {}, "file_locations": file_paths[0:1]}
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=admin_user,
        connector_specific_config=connector_config,
        access_type=access_type,
    )

    now = datetime.now(timezone.utc)
    CCPairManager.wait_for_indexing_completion(
        cc_pair, now, timeout=360, user_performing_action=admin_user
    )
    logger.info("Indexing completed successfully.")
    return cc_pair


def _create_web_connector(admin_user: DATestUser) -> None:
    """Creates a web connector."""
    # Create a web connector
    test_filename = os.path.realpath(__file__)
    test_directory = os.path.dirname(test_filename)
    with tempfile.TemporaryDirectory() as temp_dir:
        port = 8889
        website_src = os.path.join(test_directory, "resources")
        website_tgt = os.path.join(temp_dir, "resources")
        shutil.copytree(website_src, website_tgt)
        with fastapi_server_context(os.path.join(temp_dir, "resources"), port):
            sleep(1)  # sleep a tiny bit before starting everything
            hostname = os.getenv("TEST_WEB_HOSTNAME", "localhost")
            config = {
                "base_url": f"http://{hostname}:{port}/index.html",
                "web_connector_type": "single",
            }
            # store the time before we create the connector so that we know after
            # when the indexing should have started
            now = datetime.now(timezone.utc)

            # create connector
            cc_pair_1 = CCPairManager.create_from_scratch(
                source=DocumentSource.WEB,
                connector_specific_config=config,
                user_performing_action=admin_user,
            )

            CCPairManager.wait_for_indexing_completion(
                cc_pair_1, now, timeout=60, user_performing_action=admin_user
            )
    logger.info("Web connector created successfully.")


def _create_slack_user_group(
    slack_user_client: WebClient, secondary_user_client: WebClient
) -> None:
    """Creates a Slack user group."""
    # Create a user group
    user_id, _ = SlackManager.get_client_user_and_bot_ids(slack_user_client)
    secondary_user_id, _ = SlackManager.get_client_user_and_bot_ids(
        secondary_user_client
    )
    logger.info(f"Slack user ID: {user_id}")
    logger.info(f"Secondary user ID: {secondary_user_id}")
    user_group = SlackManager.create_user_group(
        slack_client=slack_user_client,
        group_name="support",
    )

    user_group_id = user_group["id"]
    SlackManager.set_user_group_members(
        slack_client=slack_user_client,
        user_group_id=user_group_id,
        user_ids=[secondary_user_id],
    )
    logger.info(f"User group created: {user_group}")


@pytest.fixture(scope="session")
def slack_test_context(reset_db_and_index) -> SlackTestContext:
    """Fixture to create the Slack test context."""
    # Create the admin user
    admin_user = _admin_user()

    # Create a Slack bot
    slack_bot = _slack_bot(admin_user)

    # Create a Slack bot client
    slack_bot_client = _slack_bot_client()

    # Create a Slack user client
    slack_user_client = _slack_user_client()

    # Create a secondary Slack user client
    slack_secondary_user_client = _slack_secondary_user_client()

    # Create standard answer and category
    std_ans_category, std_answer = _create_standard_answer_and_category(admin_user)

    # Create Slack channels
    test_channel_1, test_channel_2 = _create_slack_channels(
        slack_user_client, slack_bot_client, slack_secondary_user_client
    )

    # Create Slack channel config
    slack_channel_config = _create_slack_channel_config(
        channel_name="config-test-channel-1",
        slack_bot_id=slack_bot["id"],
        admin_user=admin_user,
    )
    # Return the context
    return SlackTestContext(
        admin_user=admin_user,
        slack_bot=slack_bot,
        slack_bot_client=slack_bot_client,
        slack_user_client=slack_user_client,
        slack_secondary_user_client=slack_secondary_user_client,
        std_ans_category=std_ans_category,
        std_answer=std_answer,
        test_channel_1=test_channel_1,
        test_channel_2=test_channel_2,
        slack_channel_config=slack_channel_config,
    )


@pytest.fixture(autouse=True, scope="session")
def setup_module(slack_test_context: SlackTestContext) -> Generator[None, None, None]:

    admin_user = slack_test_context.admin_user

    # Create LLM provider
    LLMProviderManager.create(user_performing_action=admin_user)

    # Create a file connector
    _create_file_connector(admin_user, "story.pdf")
    cc_pair = _create_file_connector(admin_user, "lucky_leaves.pdf", AccessType.PRIVATE)

    # Create a web connector
    _create_web_connector(admin_user)

    # Create a user group
    user = UserManager.create(email="subash@onyx.app")
    UserGroupManager.create(
        name="onyx-test-user-group",
        user_ids=[user.id],
        cc_pair_ids=[cc_pair.id],
        user_performing_action=admin_user,
    )

    # Create a Slack user group
    _create_slack_user_group(
        slack_user_client=slack_test_context.slack_user_client,
        secondary_user_client=slack_test_context.slack_secondary_user_client,
    )

    yield

    # This part will always run after the test, even if it fails
    # reset_all()
    logger.info("Test module teardown completed.")
