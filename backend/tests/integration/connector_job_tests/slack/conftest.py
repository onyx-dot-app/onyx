import os
from collections.abc import Generator

import pytest

from onyx.connectors.slack.models import ChannelType
from onyx.utils.threadpool_concurrency import run_in_background, wait_on_background
from tests.integration.connector_job_tests.slack.slack_api_utils import SlackManager
from tests.integration.connector_job_tests.slack.slack_channel_pool import (
    claim_pool_channels,
)

SLACK_ADMIN_EMAIL = os.environ.get("SLACK_ADMIN_EMAIL", "evan@onyx.app")
SLACK_TEST_USER_1_EMAIL = os.environ.get("SLACK_TEST_USER_1_EMAIL", "evan+1@onyx.app")
SLACK_TEST_USER_2_EMAIL = os.environ.get("SLACK_TEST_USER_2_EMAIL", "justin@onyx.app")

_BOT_TOKEN_ENV_VARS = ("SLACK_BOT_TOKEN", "SLACK_BOT_TOKEN_TEST_SPACE")


@pytest.fixture(scope="session", autouse=True)
def sweep_leaked_slack_channels() -> Generator[None, None, None]:
    """Archives leaked channels in the background; archive calls are rate limited
    separately from the calls the tests make."""
    tasks = [
        run_in_background(SlackManager.sweep_leaked_test_channels, token)
        for env_var in _BOT_TOKEN_ENV_VARS
        if (token := os.environ.get(env_var))
    ]
    yield
    for task in tasks:
        wait_on_background(task)


def _provision_slack_channels(
    bot_token: str,
) -> Generator[tuple[ChannelType, ChannelType], None, None]:
    slack_client = SlackManager.get_slack_client(bot_token)

    auth_info = slack_client.auth_test()
    print(f"\nSlack workspace: {auth_info.get('team')} ({auth_info.get('url')})")

    user_map = SlackManager.build_slack_user_email_id_map(slack_client)
    if SLACK_ADMIN_EMAIL not in user_map:
        raise KeyError(
            f"'{SLACK_ADMIN_EMAIL}' not found in Slack workspace. Available emails: {sorted(user_map.keys())}"
        )
    admin_user_id = user_map[SLACK_ADMIN_EMAIL]

    with claim_pool_channels(
        slack_client=slack_client, admin_user_id=admin_user_id
    ) as channels:
        yield channels


@pytest.fixture()
def slack_test_setup() -> Generator[tuple[ChannelType, ChannelType], None, None]:
    yield from _provision_slack_channels(os.environ["SLACK_BOT_TOKEN"])


@pytest.fixture()
def slack_perm_sync_test_setup() -> Generator[
    tuple[ChannelType, ChannelType], None, None
]:
    yield from _provision_slack_channels(os.environ["SLACK_BOT_TOKEN_TEST_SPACE"])
