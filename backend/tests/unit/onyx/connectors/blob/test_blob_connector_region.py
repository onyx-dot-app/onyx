from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

from onyx.configs.constants import BlobType
from onyx.connectors.blob.connector import BlobStorageConnector
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError


def _make_connector(region_name: str | None) -> BlobStorageConnector:
    connector = BlobStorageConnector(
        bucket_type=BlobType.S3.value,
        bucket_name="test-bucket",
        region_name=region_name,
    )
    return connector


@pytest.mark.parametrize("region_name", ["us-gov-west-1", "us-east-2", None])
def test_access_key_auth_passes_region(region_name: str | None) -> None:
    credentials: dict[str, Any] = {
        "authentication_method": "access_key",
        "aws_access_key_id": "fake-key",
        "aws_secret_access_key": "fake-secret",
    }

    connector = _make_connector(region_name)
    with patch("onyx.connectors.blob.connector.boto3.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        with patch.object(BlobStorageConnector, "_detect_bucket_region"):
            connector.load_credentials(credentials)

    mock_session.client.assert_called_once_with("s3", region_name=region_name)


@pytest.mark.parametrize("region_name", ["us-gov-west-1", None])
def test_instance_role_auth_passes_region(region_name: str | None) -> None:
    credentials: dict[str, Any] = {"authentication_method": "assume_role"}

    connector = _make_connector(region_name)
    with patch("onyx.connectors.blob.connector.boto3.client") as mock_client:
        with patch.object(BlobStorageConnector, "_detect_bucket_region"):
            connector.load_credentials(credentials)

    mock_client.assert_called_once_with("s3", region_name=region_name)


def test_iam_role_auth_passes_region_to_sts_and_s3() -> None:
    credentials: dict[str, Any] = {
        "authentication_method": "iam_role",
        "aws_role_arn": "arn:aws-us-gov:iam::123456789012:role/onyx-test",
    }

    connector = _make_connector("us-gov-west-1")
    mock_sts = MagicMock()
    mock_sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "fake-key",
            "SecretAccessKey": "fake-secret",
            "SessionToken": "fake-token",
            "Expiration": MagicMock(isoformat=lambda: "2099-01-01T00:00:00+00:00"),
        }
    }

    with (
        patch(
            "onyx.connectors.blob.connector.boto3.client", return_value=mock_sts
        ) as mock_client,
        patch("onyx.connectors.blob.connector.boto3.Session") as mock_session_cls,
        patch.object(BlobStorageConnector, "_detect_bucket_region"),
    ):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        connector.load_credentials(credentials)

    mock_client.assert_called_with("sts", region_name="us-gov-west-1")
    mock_session.client.assert_called_once_with("s3", region_name="us-gov-west-1")


def test_blank_region_normalized_to_none() -> None:
    connector = _make_connector("   ")
    assert connector.region_name is None


def _client_error(error_code: str, status_code: int) -> ClientError:
    error_response = cast(
        Any,
        {
            "Error": {"Code": error_code},
            "ResponseMetadata": {"HTTPStatusCode": status_code},
        },
    )
    return ClientError(error_response=error_response, operation_name="ListObjectsV2")


@pytest.mark.parametrize(
    "error_code, status_code",
    [("InvalidAccessKeyId", 403), ("InvalidToken", 400)],
)
def test_validation_maps_credential_rejections_to_credential_error(
    error_code: str, status_code: int
) -> None:
    connector = _make_connector(None)
    connector.s3_client = MagicMock()
    connector.s3_client.list_objects_v2.side_effect = _client_error(
        error_code, status_code
    )

    with pytest.raises(CredentialExpiredError, match=error_code):
        connector.validate_connector_settings()


def test_validation_maps_access_denied_to_insufficient_permissions() -> None:
    connector = _make_connector(None)
    connector.s3_client = MagicMock()
    connector.s3_client.list_objects_v2.side_effect = _client_error("AccessDenied", 403)

    with pytest.raises(InsufficientPermissionsError):
        connector.validate_connector_settings()


def test_govcloud_blob_link_uses_govcloud_console() -> None:
    connector = _make_connector("us-gov-west-1")
    connector.bucket_region = "us-gov-west-1"
    connector.s3_client = MagicMock()

    link = connector._get_blob_link("some/key.pdf")
    assert link.startswith("https://console.amazonaws-us-gov.com/s3/object/test-bucket")
    assert "region=us-gov-west-1" in link
