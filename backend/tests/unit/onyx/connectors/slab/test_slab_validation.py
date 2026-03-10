from unittest.mock import patch

import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.slab.connector import SlabConnector


def _build_connector(base_url: str = "https://myteam.slab.com") -> SlabConnector:
    connector = SlabConnector(base_url=base_url)
    connector.load_credentials({"slab_bot_token": "fake-token"})
    return connector


def test_validate_rejects_missing_scheme() -> None:
    connector = _build_connector(base_url="myteam.slab.com")
    with pytest.raises(ConnectorValidationError, match="https://"):
        connector.validate_connector_settings()


@patch("onyx.connectors.slab.connector.get_all_post_ids", return_value=["id1"])
def test_validate_success(mock_get_posts: object) -> None:  # noqa: ARG001
    connector = _build_connector()
    connector.validate_connector_settings()


@patch(
    "onyx.connectors.slab.connector.get_all_post_ids",
    side_effect=Exception("401 Unauthorized"),
)
def test_validate_bad_token_raises(mock_get_posts: object) -> None:  # noqa: ARG001
    connector = _build_connector()
    with pytest.raises(ConnectorValidationError, match="Failed to fetch posts"):
        connector.validate_connector_settings()
