from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
)

from onyx.connectors.azure_datalake.source_operations import (
    STORAGE_RESOURCE,
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
