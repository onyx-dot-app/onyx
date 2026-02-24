import os
from collections.abc import Generator

import pytest

from onyx.connectors.slack.models import ChannelType
from tests.integration.connector_job_tests.slack.slack_api_utils import SlackManager

SLACK_ADMIN_EMAIL = os.environ.get("SLACK_ADMIN_EMAIL", "evan@onyx.app")
SLACK_TEST_USER_1_EMAIL = os.environ.get("SLACK_TEST_USER_1_EMAIL", "evan+1@onyx.app")
SLACK_TEST_USER_2_EMAIL = os.environ.get("SLACK_TEST_USER_2_EMAIL", "justin@onyx.app")


@pytest.fixture()
def slack_test_setup() -> Generator[tuple[ChannelType, ChannelType], None, None]:
    slack_client = SlackManager.get_slack_client(os.environ["SLACK_BOT_TOKEN"])

    auth_info = slack_client.auth_test()
    print(f"\nSlack workspace: {auth_info.get('team')} ({auth_info.get('url')})")

    user_map = SlackManager.build_slack_user_email_id_map(slack_client)
    if SLACK_ADMIN_EMAIL not in user_map:
        raise KeyError(
            f"'{SLACK_ADMIN_EMAIL}' not found in Slack workspace. "
            f"Available emails: {sorted(user_map.keys())}"
        )
    admin_user_id = user_map[SLACK_ADMIN_EMAIL]

    (
        public_channel,
        private_channel,
        run_id,
    ) = SlackManager.get_and_provision_available_slack_channels(
        slack_client=slack_client, admin_user_id=admin_user_id
    )

    yield public_channel, private_channel

    # This part will always run after the test, even if it fails
    SlackManager.cleanup_after_test(slack_client=slack_client, test_id=run_id)
