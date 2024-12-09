import os
from collections.abc import Generator
from typing import Any

import pytest

from tests.integration.connector_job_tests.slack.slack_api_utils import SlackManager

# from tests.load_env_vars import load_env_vars

# load_env_vars()


@pytest.fixture()
def slack_test_setup() -> Generator[tuple[dict[str, Any], dict[str, Any]], None, None]:
    slack_client = SlackManager.get_slack_client(os.environ["SLACK_BOT_TOKEN"])
    admin_user_id = SlackManager.build_slack_user_email_id_map(slack_client)[
        "admin@onyx-test.com"
    ]

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
