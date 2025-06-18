import os
import time
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from pytest import FixtureRequest
from slack_sdk import WebClient

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.slack.connector import SlackConnector
from shared_configs.contextvars import get_current_tenant_id
from tests.daily.connectors.utils import load_everything_from_checkpoint_connector
from tests.daily.connectors.utils import to_sections
from tests.daily.connectors.utils import to_text_sections


@pytest.fixture
def mock_slack_client() -> MagicMock:
    mock = MagicMock(spec=WebClient)
    return mock


@pytest.fixture
def slack_connector(
    request: FixtureRequest,
    mock_slack_client: MagicMock,
    slack_credentials_provider: OnyxStaticCredentialsProvider,
) -> Generator[SlackConnector]:
    channel: str | None = request.param if hasattr(request, "param") else None
    connector = SlackConnector(
        channels=[channel] if channel else None,
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
    "slack_connector,expected_messages",
    [
        ["general", set()],
        ["#general", set()],
        [
            "daily-connector-test-channel",
            set(
                [
                    "Hello, world!",
                    "",
                    "Reply!",
                    "Testing again...",
                ]
            ),
        ],
        [
            "#daily-connector-test-channel",
            set(
                [
                    "Hello, world!",
                    "",
                    "Reply!",
                    "Testing again...",
                ]
            ),
        ],
    ],
    indirect=["slack_connector"],
)
def test_indexing_channels_with_message_count(
    slack_connector: SlackConnector,
    expected_messages: set[str],
) -> None:
    if not slack_connector.client:
        raise RuntimeError("Web client must be defined")

    docs = load_everything_from_checkpoint_connector(
        connector=slack_connector,
        start=0.0,
        end=time.time(),
    )

    actual_messages = set(to_text_sections(to_sections(iter(docs))))
    assert expected_messages == actual_messages


@pytest.mark.parametrize(
    "slack_connector",
    [
        # w/o hashtag
        "doesnt-exist",
        # w/ hashtag
        "#doesnt-exist",
    ],
    indirect=True,
)
def test_indexing_channels_that_dont_exist(
    slack_connector: SlackConnector,
) -> None:
    if not slack_connector.client:
        raise RuntimeError("Web client must be defined")

    with pytest.raises(
        ValueError,
        match=r"Channel '.*' not found in workspace.*",
    ):
        load_everything_from_checkpoint_connector(
            connector=slack_connector,
            start=0.0,
            end=time.time(),
        )
