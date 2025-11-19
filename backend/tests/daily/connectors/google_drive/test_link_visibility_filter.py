from collections.abc import Iterable
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.file_retrieval import DriveFileFieldType
from onyx.connectors.google_drive.file_retrieval import has_link_only_permission
from onyx.connectors.google_drive.models import DriveRetrievalStage
from onyx.connectors.google_drive.models import RetrievedDriveFile


def _stub_run_functions(
    func_with_args: Iterable[tuple], max_workers: int = 8  # noqa: ARG001
) -> list[Any]:
    return [func(*args) for func, args in func_with_args]


def _build_retrieved_file(
    permissions: list[dict[str, Any]],
) -> RetrievedDriveFile:
    return RetrievedDriveFile(
        completion_stage=DriveRetrievalStage.OAUTH_FILES,
        drive_file={
            "id": "file-id",
            "name": "Test File",
            "permissions": permissions,
        },
        user_email="user@example.com",
    )


def _prepare_connector(exclude: bool) -> GoogleDriveConnector:
    connector = GoogleDriveConnector(
        include_shared_drives=True,
        exclude_domain_link_only=exclude,
    )
    connector._creds = object()  # type: ignore[assignment]
    connector._primary_admin_email = "admin@example.com"  # type: ignore[attr-defined]
    return connector


def test_has_link_only_permission_detects_domain_link() -> None:
    file = {
        "permissions": [
            {"type": "domain", "allowFileDiscovery": False},
            {"type": "user", "emailAddress": "user@example.com"},
        ]
    }
    assert has_link_only_permission(file) is True


def test_has_link_only_permission_detects_anyone_link() -> None:
    file = {
        "permissions": [
            {"type": "anyone", "allowFileDiscovery": False},
        ]
    }
    assert has_link_only_permission(file) is True


def test_has_link_only_permission_ignores_other_permissions() -> None:
    file = {
        "permissions": [
            {"type": "domain", "allowFileDiscovery": True},
            {"type": "user", "emailAddress": "user@example.com"},
        ]
    }
    assert has_link_only_permission(file) is False


def test_connector_skips_link_only_files_when_enabled() -> None:
    connector = _prepare_connector(exclude=True)
    retrieved_file = _build_retrieved_file(
        [{"type": "domain", "allowFileDiscovery": False}]
    )
    fetch_mock = MagicMock(return_value=iter([retrieved_file]))

    with patch.object(connector, "_fetch_drive_items", fetch_mock), patch(
        "onyx.connectors.google_drive.connector.run_functions_tuples_in_parallel",
        side_effect=_stub_run_functions,
    ), patch(
        "onyx.connectors.google_drive.connector.convert_drive_item_to_document"
    ) as convert_mock:
        convert_mock.return_value = "doc"
        checkpoint = connector.build_dummy_checkpoint()
        results = list(
            connector._extract_docs_from_google_drive(
                checkpoint=checkpoint,
                start=None,
                end=None,
                include_permissions=False,
            )
        )

    assert results == []
    convert_mock.assert_not_called()
    fetch_mock.assert_called_once()
    assert (
        fetch_mock.call_args.kwargs["field_type"] == DriveFileFieldType.WITH_PERMISSIONS
    )


def test_connector_processes_files_when_option_disabled() -> None:
    connector = _prepare_connector(exclude=False)
    retrieved_file = _build_retrieved_file(
        [{"type": "domain", "allowFileDiscovery": False}]
    )
    fetch_mock = MagicMock(return_value=iter([retrieved_file]))

    with patch.object(connector, "_fetch_drive_items", fetch_mock), patch(
        "onyx.connectors.google_drive.connector.run_functions_tuples_in_parallel",
        side_effect=_stub_run_functions,
    ), patch(
        "onyx.connectors.google_drive.connector.convert_drive_item_to_document"
    ) as convert_mock:
        convert_mock.return_value = "doc"
        checkpoint = connector.build_dummy_checkpoint()
        results = list(
            connector._extract_docs_from_google_drive(
                checkpoint=checkpoint,
                start=None,
                end=None,
                include_permissions=False,
            )
        )

    assert len(results) == 1
    convert_mock.assert_called_once()
    fetch_mock.assert_called_once()
    assert fetch_mock.call_args.kwargs["field_type"] == DriveFileFieldType.STANDARD
