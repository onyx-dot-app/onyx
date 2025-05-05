import os
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from slack_sdk import WebClient

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.slack.connector import SlackConnector
from shared_configs.contextvars import get_current_tenant_id


@pytest.fixture
def mock_slack_client() -> MagicMock:
    mock = MagicMock(spec=WebClient)
    return mock


@pytest.fixture
def slack_connector(
    mock_slack_client: MagicMock,
    slack_credentials_json: OnyxStaticCredentialsProvider,
) -> Generator[SlackConnector]:
    connector = SlackConnector(
        channel_regex_enabled=False,
    )
    connector.client = mock_slack_client
    connector.set_credentials_provider(credentials_provider=slack_credentials_json)
    yield connector


@pytest.fixture
def slack_credentials_json() -> OnyxStaticCredentialsProvider:
    return OnyxStaticCredentialsProvider(
        tenant_id=get_current_tenant_id(),
        connector_name="slack",
        credential_json={
            "slack_bot_token": os.environ["SLACK_BOT_TOKEN"],
        },
    )


def test_validate_slack_connector_settings(
    slack_connector: SlackConnector,
    slack_credentials_json: OnyxStaticCredentialsProvider,
) -> None:
    slack_connector.validate_connector_settings()


@pytest.mark.parametrize(
    "channels",
    [
        # empty
        [],
        # duplicates w/ and w/o preceding hashtag
        ["danswerbot", "#danswerbot"],
    ],
)
def test_indexing_channel(
    slack_connector: SlackConnector,
    channels: list[str],
    slack_credentials_json: OnyxStaticCredentialsProvider,
) -> None:
    slack_connector.channels = channels
    slim_docs_generator = slack_connector.retrieve_all_slim_documents()
    for slim_docs in slim_docs_generator:
        # just test to make sure that the generator steps through all slim-docs appropriately
        pass
