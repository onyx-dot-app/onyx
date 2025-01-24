import os
from collections.abc import Generator
from typing import Any

import pytest

from tests.integration.connector_job_tests.slack.slack_api_utils import SlackManager

# from tests.load_env_vars import load_env_vars

# load_env_vars()


@pytest.fixture()
def slack_test_setup() -> Generator[tuple[dict[str, Any], dict[str, Any]], None, None]:
    # Get worker ID for parallel execution
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "0")

    slack_client = SlackManager.get_slack_client(os.environ["SLACK_BOT_TOKEN"])
    admin_email = (
        f"admin_{worker_id}@test.com"  # Match the email format from UserManager
    )
    email_id_map = SlackManager.build_slack_user_email_id_map(slack_client)
    if admin_email not in email_id_map:
        raise ValueError(
            f"Admin user with email {admin_email} not found in Slack. "
            f"Available emails: {list(email_id_map.keys())}"
        )
    admin_user_id = email_id_map[admin_email]

    (
        public_channel,
        private_channel,
        run_id,
    ) = SlackManager.get_and_provision_available_slack_channels(
        slack_client=slack_client,
        admin_user_id=admin_user_id,
        channel_prefix=f"test_{worker_id}",  # Make channels unique per worker
    )

    yield public_channel, private_channel

    # This part will always run after the test, even if it fails
    SlackManager.cleanup_after_test(slack_client=slack_client, test_id=run_id)
