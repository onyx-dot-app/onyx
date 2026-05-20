from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from pytest import FixtureRequest
from slack_sdk import WebClient

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.slack.connector import SlackConnector
from shared_configs.contextvars import get_current_tenant_id
from tests.utils.secret_names import TestSecret


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
        use_redis=False,
    )
    connector.client = mock_slack_client
    connector.set_credentials_provider(credentials_provider=slack_credentials_provider)
    yield connector


@pytest.fixture
def slack_credentials_provider(
    test_secrets: dict[TestSecret, str],
) -> OnyxStaticCredentialsProvider:
    return OnyxStaticCredentialsProvider(
        tenant_id=get_current_tenant_id(),
        connector_name="slack",
        credential_json={
            "slack_bot_token": test_secrets[TestSecret.SLACK_BOT_TOKEN],
        },
    )
