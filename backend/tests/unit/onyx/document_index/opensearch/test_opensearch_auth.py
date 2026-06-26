import importlib
import os
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from opensearchpy import Urllib3AWSV4SignerAuth

import onyx.configs.app_configs as app_configs
from onyx.document_index.opensearch.client import OpenSearchClient
from onyx.document_index.opensearch.constants import OpenSearchAuthMethod

_OS_AUTH_ENV = (
    "OPENSEARCH_AUTH_METHOD",
    "OPENSEARCH_AWS_REGION",
    "OPENSEARCH_AWS_SERVICE",
)


def test_iam_auth_uses_sigv4_signer() -> None:
    """
    IAM auth must hand opensearch-py a SigV4 signer built from boto3
    credentials, not a username/password tuple.
    """
    with (
        patch("onyx.document_index.opensearch.client.OpenSearch") as mock_os,
        patch("onyx.document_index.opensearch.client.boto3.Session") as mock_session,
    ):
        mock_session.return_value.get_credentials.return_value = MagicMock()
        OpenSearchClient(
            host="h",
            auth_method=OpenSearchAuthMethod.IAM,
            aws_region="us-east-1",
            aws_service="es",
        )
        assert isinstance(mock_os.call_args.kwargs["http_auth"], Urllib3AWSV4SignerAuth)


def test_basic_auth_uses_tuple() -> None:
    """
    Back-compat: basic auth keeps passing the (username, password) tuple
    straight through to opensearch-py.
    """
    with patch("onyx.document_index.opensearch.client.OpenSearch") as mock_os:
        OpenSearchClient(
            host="h",
            auth=("u", "p"),
            auth_method=OpenSearchAuthMethod.BASIC,
        )
        assert mock_os.call_args.kwargs["http_auth"] == ("u", "p")


def test_iam_without_region_raises() -> None:
    with pytest.raises(ValueError, match="aws_region is required"):
        OpenSearchClient(
            host="h",
            auth_method=OpenSearchAuthMethod.IAM,
            aws_region=None,
        )


def test_iam_without_credentials_raises() -> None:
    with patch("onyx.document_index.opensearch.client.boto3.Session") as mock_session:
        mock_session.return_value.get_credentials.return_value = None
        with pytest.raises(ValueError, match="no AWS credentials"):
            OpenSearchClient(
                host="h",
                auth_method=OpenSearchAuthMethod.IAM,
                aws_region="us-east-1",
            )


def _clear_os_auth_env() -> None:
    for var in _OS_AUTH_ENV:
        os.environ.pop(var, None)


def test_iam_config_without_region_raises() -> None:
    with patch.dict(os.environ, {}, clear=False):
        _clear_os_auth_env()
        os.environ["OPENSEARCH_AUTH_METHOD"] = "iam"

        with pytest.raises(ValueError, match="OPENSEARCH_AWS_REGION must be set"):
            importlib.reload(app_configs)
    importlib.reload(app_configs)
