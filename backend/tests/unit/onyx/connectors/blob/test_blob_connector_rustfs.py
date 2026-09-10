from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import BlobType
from onyx.connectors.blob.connector import BlobStorageConnector
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.utils.url import SSRFException


def _make_connector(endpoint_url: str = "http://rustfs:9000/") -> BlobStorageConnector:
    return BlobStorageConnector(
        bucket_type=BlobType.RUSTFS.value,
        bucket_name="documents",
        prefix="research",
        endpoint_url=endpoint_url,
        region_name="us-east-1",
    )


def test_rustfs_uses_custom_endpoint_and_path_style() -> None:
    connector = _make_connector()
    with (
        patch(
            "onyx.connectors.blob.connector.web_connector_ssrf_enforced",
            return_value=False,
        ),
        patch(
            "onyx.connectors.blob.connector.validate_outbound_http_url",
            return_value="http://rustfs:9000/",
        ) as mock_validate,
        patch("onyx.connectors.blob.connector.boto3.client") as mock_client,
    ):
        connector.load_credentials(
            {"access_key": "rustfs-access-key", "secret_key": "rustfs-secret-key"}
        )

    mock_validate.assert_called_once_with(
        "http://rustfs:9000/",
        allow_private_network=True,
        block_link_local_only=True,
    )
    _, kwargs = mock_client.call_args
    assert kwargs["endpoint_url"] == "http://rustfs:9000"
    assert kwargs["region_name"] == "us-east-1"
    assert kwargs["config"].s3["addressing_style"] == "path"


@pytest.mark.parametrize("missing_key", ["access_key", "secret_key"])
def test_rustfs_requires_both_credentials(missing_key: str) -> None:
    credentials = {
        "access_key": "rustfs-access-key",
        "secret_key": "rustfs-secret-key",
    }
    del credentials[missing_key]

    with pytest.raises(ConnectorMissingCredentialError):
        _make_connector().load_credentials(credentials)


def test_rustfs_requires_an_endpoint() -> None:
    with pytest.raises(ConnectorValidationError, match="endpoint URL is required"):
        _make_connector(endpoint_url="").load_credentials(
            {"access_key": "key", "secret_key": "secret"}
        )


def test_rustfs_rejects_unsafe_endpoint() -> None:
    with (
        patch(
            "onyx.connectors.blob.connector.web_connector_ssrf_enforced",
            return_value=True,
        ),
        patch(
            "onyx.connectors.blob.connector.validate_outbound_http_url",
            side_effect=SSRFException("Access to internal/private IP is not allowed."),
        ),
        pytest.raises(ConnectorValidationError, match="Invalid RustFS endpoint URL"),
    ):
        _make_connector(endpoint_url="http://169.254.169.254").load_credentials(
            {"access_key": "key", "secret_key": "secret"}
        )


def test_rustfs_poll_skips_unchanged_objects() -> None:
    connector = _make_connector()
    client = MagicMock()
    connector.s3_client = client
    now = datetime.now(timezone.utc)
    client.get_paginator.return_value.paginate.return_value = [
        {
            "Contents": [
                {
                    "Key": "research/unchanged.pdf",
                    "LastModified": now - timedelta(hours=2),
                }
            ]
        }
    ]

    assert (
        list(
            connector.poll_source(
                (now - timedelta(hours=1)).timestamp(),
                now.timestamp(),
            )
        )
        == []
    )
    client.get_object.assert_not_called()


def test_rustfs_does_not_expose_private_object_links() -> None:
    assert _make_connector()._get_blob_link("research/paper.pdf") == ""
