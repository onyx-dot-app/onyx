import os
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from slack_sdk import WebClient

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.slack.connector import default_msg_filter
from onyx.connectors.slack.connector import filter_channels
from onyx.connectors.slack.connector import get_channel_messages
from onyx.connectors.slack.connector import get_channels
from onyx.connectors.slack.connector import SlackConnector
from shared_configs.contextvars import get_current_tenant_id


@pytest.fixture
def mock_slack_client() -> MagicMock:
    mock = MagicMock(spec=WebClient)
    return mock


@pytest.fixture
def slack_connector(
    mock_slack_client: MagicMock,
    slack_credentials_provider: OnyxStaticCredentialsProvider,
) -> Generator[SlackConnector]:
    connector = SlackConnector(
        channel_regex_enabled=False,
    )
    connector.client = mock_slack_client
    connector.set_credentials_provider(credentials_provider=slack_credentials_provider)
    yield connector


@pytest.fixture
def slack_credentials_provider() -> OnyxStaticCredentialsProvider:
    CI_ENV_VAR = "SLACK_BOT_TOKEN"
    LOCAL_ENV_VAR = "DANSWER_BOT_SLACK_BOT_TOKEN"

    slack_bot_token = os.environ.get(CI_ENV_VAR, os.environ.get(LOCAL_ENV_VAR))
    if not slack_bot_token:
        raise RuntimeError(
            f"No slack credentials found; either set the {CI_ENV_VAR} env-var or the {LOCAL_ENV_VAR} env-var"
        )

    return OnyxStaticCredentialsProvider(
        tenant_id=get_current_tenant_id(),
        connector_name="slack",
        credential_json={
            "slack_bot_token": slack_bot_token,
        },
    )


def test_validate_slack_connector_settings(
    slack_connector: SlackConnector,
) -> None:
    slack_connector.validate_connector_settings()


@pytest.mark.parametrize(
    "channel_name,expected_messages",
    [
        ("general", set()),
        ("#general", set()),
        (
            "daily-connector-test-channel",
            set(
                [
                    "Hello, world!",
                    "",
                    "Testing again...",
                ]
            ),
        ),
        (
            "#daily-connector-test-channel",
            set(
                [
                    "Hello, world!",
                    "",
                    "Testing again...",
                ]
            ),
        ),
    ],
)
def test_indexing_channels_with_message_count(
    slack_connector: SlackConnector,
    channel_name: str,
    expected_messages: set[str],
) -> None:
    if not slack_connector.client:
        raise RuntimeError("Web client must be defined")

    slack_connector.channels = [channel_name]

    channels = get_channels(client=slack_connector.client, get_private=False)
    [channel_info] = filter_channels(
        all_channels=channels,
        channels_to_connect=slack_connector.channels,
        regex_enabled=False,
    )
    channel_id = channel_info.get("id")
    if not channel_id:
        raise RuntimeError("Channel id not present")

    actual_messages = set(
        message_type["text"]
        for message_types in get_channel_messages(
            client=slack_connector.client, channel=channel_info
        )
        for message_type in message_types
        if not default_msg_filter(message_type) and "text" in message_type
    )

    assert expected_messages == actual_messages


@pytest.mark.parametrize(
    "channel_name",
    [
        # w/o hashtag
        "doesnt-exist",
        # w/ hashtag
        "#doesnt-exist",
    ],
)
def test_indexing_channels_that_dont_exist(
    slack_connector: SlackConnector,
    channel_name: str,
) -> None:
    if not slack_connector.client:
        raise RuntimeError("Web client must be defined")

    slack_connector.channels = [channel_name]
    sanitized_channel_name = channel_name.removeprefix("#")
    with pytest.raises(
        ValueError,
        match=rf"Channel '{sanitized_channel_name}' not found in workspace.*",
    ):
        channels = get_channels(client=slack_connector.client, get_private=False)
        filter_channels(
            all_channels=channels,
            channels_to_connect=slack_connector.channels,
            regex_enabled=False,
        )
