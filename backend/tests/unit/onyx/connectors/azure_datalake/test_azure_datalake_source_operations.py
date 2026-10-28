from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
)

from onyx.connectors.azure_datalake.source_operations import (
    STORAGE_RESOURCE,
    AzureDataLakeNotFoundError,
    AzureDataLakeRequestError,
    AzureDataLakeSourceOperations,
)
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    UnreachableValidationError,
)

MODULE = "onyx.connectors.azure_datalake.source_operations"
CONFIG = {"account_name": "onyxtest", "container_name": "docs"}


def _gateway(
    credential_json: dict[str, Any], config: dict[str, Any] = CONFIG
) -> AzureDataLakeSourceOperations:
    return AzureDataLakeSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            tenant_id=None,
            connector_name="azure_datalake",
            credential_json=credential_json,
        ),
        connector_specific_config=config,
    )


def _storage_error(
    status: int, code: str, error_class: type[HttpResponseError] = HttpResponseError
) -> HttpResponseError:
    response = MagicMock(status_code=status, reason="Reason")
    error = error_class(message=code, response=response)
    error.error_code = code  # ty: ignore[unresolved-attribute]
    return error


def _raising(error: Exception) -> Any:
    def action() -> None:
        raise error

    return action


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            _storage_error(403, "AuthenticationFailed", ClientAuthenticationError),
            CredentialInvalidError,
        ),
        (
            _storage_error(403, "AuthorizationPermissionMismatch"),
            InsufficientPermissionsError,
        ),
        (_storage_error(404, "FilesystemNotFound"), ConnectorValidationError),
        (_storage_error(404, "PathNotFound"), ConnectorValidationError),
        (ServiceRequestError("no such host"), UnreachableValidationError),
        (_storage_error(500, "InternalError"), AzureDataLakeRequestError),
    ],
)
def test_storage_errors_map_to_the_validation_family(
    error: Exception, expected: type[Exception]
) -> None:
    gateway = _gateway({})

    with pytest.raises(expected):
        gateway._call(_raising(error), "the path 'x'")


def test_a_missing_container_names_the_container() -> None:
    gateway = _gateway({})

    with pytest.raises(ConnectorValidationError, match="'docs'.*'onyxtest'"):
        gateway._call(_raising(_storage_error(404, "ContainerNotFound")), "x")


def test_an_account_key_signs_requests_itself() -> None:
    # The sign-in check runs before a container is chosen.
    gateway = _gateway(
        {
            "authentication_method": "account_key",
            "adls_account_name": "onyxtest",
            "adls_account_key": "key",
        },
        config={"account_name": "onyxtest"},
    )

    with patch(f"{MODULE}.DataLakeServiceClient") as client_class:
        token = gateway.check_sign_in()

    assert token is None
    assert client_class.call_args.kwargs["credential"] == "key"
    assert client_class.call_args.kwargs["account_url"] == (
        "https://onyxtest.dfs.core.windows.net"
    )


def test_an_app_registration_gets_a_storage_token() -> None:
    gateway = _gateway(
        {
            "authentication_method": "client_secret",
            "adls_client_id": "client",
            "adls_directory_id": "tenant",
            "adls_client_secret": "secret",
        }
    )
    token = {"access_token": "header.e30.signature", "expires_in": 3600}

    with (
        patch(f"{MODULE}.build_graph_auth_context") as build_context,
        patch(f"{MODULE}.acquire_token_response", return_value=token) as acquire,
        patch(f"{MODULE}.DataLakeServiceClient") as client_class,
    ):
        gateway.check_sign_in()
        gateway._service()
        storage_credential = client_class.call_args.kwargs["credential"]
        access_token = storage_credential.get_token(f"{STORAGE_RESOURCE}/.default")

    assert build_context.call_args.kwargs["client_secret"] == "secret"
    assert all(call.args[1] == STORAGE_RESOURCE for call in acquire.call_args_list)
    assert access_token.token == "header.e30.signature"


def test_a_credential_with_an_unknown_method_is_invalid() -> None:
    gateway = _gateway({"authentication_method": "password"})

    with pytest.raises(CredentialInvalidError):
        gateway.check_sign_in()


_APP_CREDENTIAL: dict[str, Any] = {
    "authentication_method": "client_secret",
    "adls_client_id": "client",
    "adls_directory_id": "tenant",
    "adls_client_secret": "secret",
}


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_http_error(401), CredentialInvalidError),
        (_http_error(403), InsufficientPermissionsError),
        (_http_error(404), AzureDataLakeNotFoundError),
        (_http_error(500), AzureDataLakeRequestError),
        (requests.ConnectionError("reset"), UnreachableValidationError),
    ],
)
def test_resource_manager_errors_map_to_the_validation_family(
    error: Exception, expected: type[Exception]
) -> None:
    gateway = _gateway(_APP_CREDENTIAL)

    with (
        patch(f"{MODULE}.build_graph_auth_context"),
        patch(f"{MODULE}.graph_api_get_json", side_effect=error),
        pytest.raises(expected),
    ):
        gateway.list_role_assignments(scope="/subscriptions/sub")


def test_role_assignments_follow_next_link_and_read_properties() -> None:
    gateway = _gateway(_APP_CREDENTIAL)
    pages = [
        {
            "value": [
                {
                    "id": "a1",
                    "properties": {
                        "principalId": "user",
                        "principalType": "User",
                        "roleDefinitionId": "/role",
                        "scope": "/subscriptions/sub",
                        "condition": "@Resource[x]",
                    },
                }
            ],
            "nextLink": "https://management.azure.com/next",
        },
        {"value": [{"id": "a2", "properties": {"principalId": "group"}}]},
    ]

    with (
        patch(f"{MODULE}.build_graph_auth_context"),
        patch(f"{MODULE}.graph_api_get_json", side_effect=pages) as get_json,
    ):
        assignments = gateway.list_role_assignments(scope="/subscriptions/sub")

    assert [a.id for a in assignments] == ["a1", "a2"]
    assert assignments[0].principal_type == "User"
    assert assignments[0].condition == "@Resource[x]"
    assert get_json.call_args_list[0].args[1] == (
        "https://management.azure.com/subscriptions/sub/providers/"
        "Microsoft.Authorization/roleAssignments"
    )
    assert get_json.call_args_list[0].args[2]["$filter"] == "atScope()"
    assert get_json.call_args_list[1].args[2] is None


def test_account_key_cannot_read_resource_manager() -> None:
    gateway = _gateway(
        {
            "authentication_method": "account_key",
            "adls_account_name": "onyxtest",
            "adls_account_key": "a2V5",
        }
    )

    with pytest.raises(CredentialInvalidError, match="app registration"):
        gateway.list_subscriptions()


@pytest.mark.parametrize(("size", "expected"), [(3, b"raw"), (11, None)])
def test_read_file_reads_stored_bytes_up_to_the_limit(
    size: int, expected: bytes | None
) -> None:
    gateway = _gateway(
        {
            "authentication_method": "account_key",
            "adls_account_name": "onyxtest",
            "adls_account_key": "key",
        }
    )

    with patch(f"{MODULE}.DataLakeServiceClient") as client_class:
        file_system = client_class.return_value.get_file_system_client.return_value
        file_client = file_system.get_file_client.return_value
        downloader = file_client.download_file.return_value
        downloader.size = size
        downloader.properties.last_modified = datetime(2026, 1, 1, tzinfo=timezone.utc)
        downloader.readall.return_value = b"raw"
        result = gateway.read_file(path="docs/a.txt.gz", max_bytes=10)

    # A gzip-encoded file is not expanded in memory before the size check.
    file_client.download_file.assert_called_once_with(decompress=False)
    assert result.content == expected
