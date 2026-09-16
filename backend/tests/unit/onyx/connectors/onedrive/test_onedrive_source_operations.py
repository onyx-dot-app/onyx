from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests
from fastapi import UploadFile

from onyx.connectors.microsoft_utils.drive_delta import (
    DRIVE_DELTA_SELECT_FIELDS,
    HIERARCHICAL_SHARING_PREFERENCE,
    PREFER_HEADER,
    build_delta_start_url,
)
from onyx.connectors.microsoft_utils.graph_auth import MicrosoftAuthMethod
from onyx.connectors.microsoft_utils.graph_client import GraphApiClient
from onyx.connectors.microsoft_utils.graph_errors import INVALID_CERTIFICATE_CODE
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftAuthError as OneDriveAuthError,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError as OneDriveGraphError,
)
from onyx.connectors.onedrive.models import OneDriveCredentials
from onyx.connectors.onedrive.source_operations import OneDriveSourceOperations
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.private_key_types import (
    FILE_TYPE_TO_FILE_PROCESSOR,
    PrivateKeyFileTypes,
    process_pkcs12_private_key_file,
    process_sharepoint_private_key_file,
)


def _gateway() -> tuple[OneDriveSourceOperations, Any]:
    provider = MagicMock()
    provider.get_credentials.return_value = OneDriveCredentials(
        onedrive_client_id="client",
        onedrive_directory_id="tenant",
        onedrive_client_secret="secret",
    ).model_dump()
    gateway = OneDriveSourceOperations(credentials_provider=provider)
    client = MagicMock(spec=GraphApiClient)
    client.graph_api_base = "https://graph.microsoft.com/v1.0"
    gateway._gateway()._client = client
    return gateway, client


def test_onedrive_delta_uses_preferences_next_link_and_ignores_delta_link() -> None:
    gateway, client = _gateway()
    client.get_json.return_value = {
        "value": [],
        "@odata.nextLink": "https://graph.microsoft.com/next",
        "@odata.deltaLink": "https://graph.microsoft.com/delta",
    }

    result = gateway.get_delta_page(
        drive_id="drive",
        page_url="https://graph.microsoft.com/start",
        page_size=17,
    )

    assert result.next_cursor == "https://graph.microsoft.com/next"
    headers = client.get_json.call_args.args[2]
    assert HIERARCHICAL_SHARING_PREFERENCE in headers[PREFER_HEADER]

    client.get_json.return_value = {
        "value": [],
        "@odata.deltaLink": "https://graph.microsoft.com/delta",
    }
    result = gateway.get_delta_page(
        drive_id="drive",
        page_url="https://graph.microsoft.com/next",
        page_size=17,
    )
    assert result.next_cursor is None


def test_onedrive_delta_410_uses_safe_full_resync_cursor() -> None:
    gateway, client = _gateway()
    response = requests.Response()
    response.status_code = 410
    response.url = "https://graph.microsoft.com/v1.0/drives/drive/root/delta"
    response.headers["Location"] = "https://attacker.example/delta"
    error = requests.HTTPError(response=response)
    client.get_json.side_effect = error

    result = gateway.get_delta_page(
        drive_id="drive",
        page_url="https://graph.microsoft.com/v1.0/drives/drive/root/delta?token=x",
        page_size=17,
    )

    assert result.resynced
    assert result.next_cursor is not None
    assert result.next_cursor.startswith(
        "https://graph.microsoft.com/v1.0/drives/drive/root/delta?"
    )
    assert "$top=17" in result.next_cursor
    assert f"$select={DRIVE_DELTA_SELECT_FIELDS}" in result.next_cursor


def test_onedrive_delta_start_url_uses_sharing_fields_and_page_size() -> None:
    url = build_delta_start_url(
        "https://graph.microsoft.com/v1.0",
        "drive",
        page_size=23,
        select_fields=DRIVE_DELTA_SELECT_FIELDS,
    )

    assert "$top=23" in url
    assert f"$select={DRIVE_DELTA_SELECT_FIELDS}" in url


def test_onedrive_preserves_msal_throttle_status() -> None:
    gateway, _ = _gateway()

    with patch(
        "onyx.connectors.microsoft_utils.graph_auth.build_msal_app",
        side_effect=ValueError("authority discovery failed; HTTP status: 429"),
    ):
        with pytest.raises(OneDriveGraphError) as raised:
            _ = gateway._gateway().auth_context

    assert raised.value.status == 429


def test_onedrive_source_operation_inventory_marks_pr6_operations_untested() -> None:
    specs = OneDriveSourceOperations.operation_specs()

    assert set(specs) == {
        "check_token",
        "list_users",
        "get_user",
        "get_default_drive",
        "get_delta_page",
        "download_item",
        "list_permissions",
        "list_transitive_group_members",
    }
    assert "document context" in (specs["list_permissions"].untested or "")
    assert "concrete group id" in (
        specs["list_transitive_group_members"].untested or ""
    )


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        (None, MicrosoftAuthMethod.CLIENT_SECRET),
        ("certificate", MicrosoftAuthMethod.CERTIFICATE),
    ],
)
def test_onedrive_builds_both_app_only_auth_methods(
    method: str | None, expected: MicrosoftAuthMethod
) -> None:
    provider = MagicMock()
    provider.get_credentials.return_value = OneDriveCredentials(
        onedrive_client_id="client",
        onedrive_directory_id="tenant",
        onedrive_client_secret="secret",
        onedrive_authentication_method=method,
        onedrive_private_key="Y2VydA==",
        onedrive_certificate_password="password",
    ).model_dump()
    gateway = OneDriveSourceOperations(credentials_provider=provider)

    with patch(
        "onyx.connectors.microsoft_utils.graph_auth.build_msal_app",
        return_value=MagicMock(),
    ) as build:
        _ = gateway._gateway().auth_context

    assert build.call_args.kwargs["auth_method"] is expected


def test_onedrive_classifies_invalid_certificate() -> None:
    provider = MagicMock()
    provider.get_credentials.return_value = OneDriveCredentials(
        onedrive_client_id="client",
        onedrive_directory_id="tenant",
        onedrive_authentication_method="certificate",
        onedrive_private_key="Y2VydA==",
        onedrive_certificate_password="password",
    ).model_dump()
    gateway = OneDriveSourceOperations(credentials_provider=provider)

    with patch(
        "onyx.connectors.microsoft_utils.graph_auth.build_msal_app",
        side_effect=RuntimeError("Failed to load certificate"),
    ):
        with pytest.raises(OneDriveAuthError) as raised:
            _ = gateway._gateway().auth_context

    assert raised.value.code == INVALID_CERTIFICATE_CODE


def test_onedrive_accepts_standard_and_legacy_authentication_method_keys() -> None:
    standard = OneDriveCredentials.model_validate(
        {
            "onedrive_client_id": "client",
            "onedrive_directory_id": "tenant",
            "authentication_method": "certificate",
        }
    )
    legacy = OneDriveCredentials.model_validate(
        {
            "onedrive_client_id": "client",
            "onedrive_directory_id": "tenant",
            "onedrive_authentication_method": "client_secret",
        }
    )

    assert standard.onedrive_authentication_method == "certificate"
    assert legacy.onedrive_authentication_method == "client_secret"


def test_onedrive_uses_shared_pkcs12_processor() -> None:
    assert (
        FILE_TYPE_TO_FILE_PROCESSOR[PrivateKeyFileTypes.ONEDRIVE_PFX_FILE]
        is FILE_TYPE_TO_FILE_PROCESSOR[PrivateKeyFileTypes.SHAREPOINT_PFX_FILE]
    )
    assert process_sharepoint_private_key_file is process_pkcs12_private_key_file


@pytest.mark.parametrize(
    ("filename", "is_valid"),
    [
        ("certificate.pem", True),
        ("certificate.pfx", False),
    ],
)
def test_pkcs12_processor_raises_typed_input_errors(
    filename: str, is_valid: bool
) -> None:
    upload = UploadFile(BytesIO(b"not-a-certificate"), filename=filename)

    with (
        patch(
            "onyx.server.documents.private_key_types.validate_pkcs12_content",
            return_value=is_valid,
        ),
        pytest.raises(OnyxError) as exc_info,
    ):
        process_pkcs12_private_key_file(upload)

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT
