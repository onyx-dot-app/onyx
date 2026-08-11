from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.lark.connector import LarkConnector
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document


def _response(payload: dict[str, Any], status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


def _authenticated_connector() -> tuple[LarkConnector, MagicMock]:
    request_client = MagicMock()
    request_client.post.return_value = _response(
        {"code": 0, "tenant_access_token": "tenant-token"}
    )
    connector = LarkConnector(folder_token="folder-token", batch_size=10)
    with patch("onyx.connectors.lark.connector.rl_requests", request_client):
        connector.load_credentials(
            {"lark_app_id": "cli_test", "lark_app_secret": "secret"}
        )
    return connector, request_client


def test_load_credentials_fetches_tenant_access_token() -> None:
    connector, request_client = _authenticated_connector()

    assert connector.client._tenant_access_token == "tenant-token"
    request_client.post.assert_called_once_with(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": "cli_test", "app_secret": "secret"},
        timeout=30,
    )


def test_load_credentials_requires_app_credentials() -> None:
    connector = LarkConnector()

    with pytest.raises(ConnectorMissingCredentialError, match="Lark app ID"):
        connector.load_credentials({"lark_app_secret": "secret"})


def test_validate_connector_lists_the_app_root_without_a_folder_token() -> None:
    connector, request_client = _authenticated_connector()
    connector.folder_token = None
    request_client.get.return_value = _response(
        {"code": 0, "data": {"files": [], "has_more": False}}
    )

    with patch("onyx.connectors.lark.connector.rl_requests", request_client):
        connector.validate_connector_settings()

    assert request_client.get.call_args.kwargs["params"] == {"page_size": 1}


def test_load_from_state_paginates_and_converts_doc_and_docx() -> None:
    connector, request_client = _authenticated_connector()
    request_client.get.side_effect = [
        _response(
            {
                "code": 0,
                "data": {
                    "files": [
                        {
                            "token": "docx-token",
                            "name": "Architecture",
                            "type": "docx",
                            "url": "https://example.larksuite.com/docx/docx-token",
                            "created_time": "1717200000000",
                            "modified_time": "1717286400000",
                        },
                        {"token": "sheet-token", "name": "Sheet", "type": "sheet"},
                    ],
                    "has_more": True,
                    "page_token": "next-page",
                },
            }
        ),
        _response({"code": 0, "data": {"content": "# System design"}}),
        _response(
            {
                "code": 0,
                "data": {
                    "files": [
                        {
                            "token": "doc-token",
                            "name": "Runbook",
                            "type": "doc",
                            "modified_time": "1717372800000",
                        }
                    ],
                    "has_more": False,
                },
            }
        ),
        _response({"code": 0, "data": {"raw_content": "Restart procedure"}}),
    ]

    with patch("onyx.connectors.lark.connector.rl_requests", request_client):
        batches = list(connector.load_from_state())

    documents = [
        item for batch in batches for item in batch if isinstance(item, Document)
    ]
    assert [document.id for document in documents] == [
        "lark-docx-docx-token",
        "lark-doc-doc-token",
    ]
    assert documents[0].source == DocumentSource.LARK
    assert documents[0].sections[0].text == "Architecture\n\n# System design"
    assert documents[1].sections[0].text == "Runbook\n\nRestart procedure"
    assert documents[0].doc_updated_at is not None
    assert documents[0].doc_updated_at.timestamp() == 1_717_286_400

    first_list_call = request_client.get.call_args_list[0]
    assert first_list_call.args[0].endswith("/drive/v1/files")
    assert first_list_call.kwargs["params"] == {
        "page_size": 200,
        "folder_token": "folder-token",
    }
    second_list_call = request_client.get.call_args_list[2]
    assert second_list_call.kwargs["params"]["page_token"] == "next-page"


def test_poll_source_only_reads_documents_updated_in_window() -> None:
    connector, request_client = _authenticated_connector()
    request_client.get.side_effect = [
        _response(
            {
                "code": 0,
                "data": {
                    "files": [
                        {
                            "token": "old-doc",
                            "name": "Old",
                            "type": "docx",
                            "modified_time": "1717200000000",
                        },
                        {
                            "token": "new-doc",
                            "name": "New",
                            "type": "docx",
                            "modified_time": "1717286400000",
                        },
                    ],
                    "has_more": False,
                },
            }
        ),
        _response({"code": 0, "data": {"content": "New content"}}),
    ]

    with patch("onyx.connectors.lark.connector.rl_requests", request_client):
        batches = list(connector.poll_source(start=1_717_200_000, end=1_717_300_000))

    documents = [
        item for batch in batches for item in batch if isinstance(item, Document)
    ]
    assert [document.id for document in documents] == ["lark-docx-new-doc"]
    assert request_client.get.call_count == 2


def test_load_from_state_traverses_nested_folders() -> None:
    connector, request_client = _authenticated_connector()
    request_client.get.side_effect = [
        _response(
            {
                "code": 0,
                "data": {
                    "files": [
                        {
                            "token": "nested-folder-token",
                            "name": "Engineering",
                            "type": "folder",
                        }
                    ],
                    "has_more": False,
                },
            }
        ),
        _response(
            {
                "code": 0,
                "data": {
                    "files": [
                        {
                            "token": "nested-doc-token",
                            "name": "Design",
                            "type": "docx",
                            "modified_time": "1717286400000",
                        }
                    ],
                    "has_more": False,
                },
            }
        ),
        _response({"code": 0, "data": {"content": "Design content"}}),
    ]

    with patch("onyx.connectors.lark.connector.rl_requests", request_client):
        batches = list(connector.load_from_state())

    documents = [
        item for batch in batches for item in batch if isinstance(item, Document)
    ]
    assert [document.id for document in documents] == ["lark-docx-nested-doc-token"]
    assert request_client.get.call_args_list[1].kwargs["params"]["folder_token"] == (
        "nested-folder-token"
    )


def test_validate_connector_maps_forbidden_response_to_permission_error() -> None:
    connector, request_client = _authenticated_connector()
    request_client.get.return_value = _response(
        {"code": 99991672, "msg": "permission denied"}, status_code=403
    )

    with (
        patch("onyx.connectors.lark.connector.rl_requests", request_client),
        pytest.raises(InsufficientPermissionsError, match="does not have permission"),
    ):
        connector.validate_connector_settings()
