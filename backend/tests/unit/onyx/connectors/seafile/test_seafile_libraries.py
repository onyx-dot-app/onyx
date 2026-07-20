from unittest.mock import Mock

import pytest
import requests

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.seafile import libraries as seafile_libraries
from onyx.connectors.seafile.libraries import list_libraries_from_seafile
from onyx.connectors.seafile.libraries import SeafileLibraryListingError


def _response_with_json(data: object) -> Mock:
    response = Mock()
    response.json.return_value = data
    return response


def _http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    response._content = b"upstream error"
    return requests.HTTPError(response=response)


def test_list_seafile_libraries_maps_common_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_request = Mock(
        return_value=_response_with_json(
            [
                {"id": "repo-1", "name": "Engineering", "owner": "admin"},
                {"repo_id": "repo-2", "repo_name": "Product"},
                {"id": "", "name": "Missing ID"},
                {"id": "repo-3"},
            ]
        )
    )
    monkeypatch.setattr(seafile_libraries, "request_with_retries", mock_request)

    libraries = list_libraries_from_seafile("https://seafile.example.com/", "token")

    assert [library.model_dump() for library in libraries] == [
        {"id": "repo-1", "name": "Engineering", "owner": "admin"},
        {"id": "repo-2", "name": "Product", "owner": None},
    ]
    mock_request.assert_called_once_with(
        method="GET",
        url="https://seafile.example.com/api2/repos/",
        headers={"Authorization": "Token token"},
    )


@pytest.mark.parametrize("invalid_base_url", ["", "seafile.example.com"])
def test_list_seafile_libraries_rejects_invalid_base_url(
    invalid_base_url: str,
) -> None:
    with pytest.raises(ConnectorValidationError):
        list_libraries_from_seafile(invalid_base_url, "token")


@pytest.mark.parametrize(
    ("status_code", "exception_type"),
    [
        (401, CredentialExpiredError),
        (403, InsufficientPermissionsError),
        (500, SeafileLibraryListingError),
    ],
)
def test_list_seafile_libraries_maps_upstream_errors(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    exception_type: type[Exception],
) -> None:
    monkeypatch.setattr(
        seafile_libraries,
        "request_with_retries",
        Mock(side_effect=_http_error(status_code)),
    )

    with pytest.raises(exception_type):
        list_libraries_from_seafile("https://seafile.example.com", "token")


def test_list_seafile_libraries_rejects_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = Mock()
    response.json.side_effect = ValueError("not json")
    monkeypatch.setattr(
        seafile_libraries, "request_with_retries", Mock(return_value=response)
    )

    with pytest.raises(SeafileLibraryListingError) as exc_info:
        list_libraries_from_seafile("https://seafile.example.com", "token")

    assert "malformed JSON" in str(exc_info.value)


def test_list_seafile_libraries_allows_empty_library_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        seafile_libraries,
        "request_with_retries",
        Mock(return_value=_response_with_json([])),
    )

    assert list_libraries_from_seafile("https://seafile.example.com", "token") == []
