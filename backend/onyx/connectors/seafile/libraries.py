from typing import Any

import requests
from pydantic import BaseModel

from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.seafile.connector import normalize_seafile_base_url
from onyx.utils.retry_wrapper import request_with_retries


class SeafileLibrary(BaseModel):
    id: str
    name: str
    owner: str | None = None


class SeafileLibraryListingError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _extract_seafile_library(item: dict[str, Any]) -> SeafileLibrary | None:
    raw_id = item.get("id") or item.get("repo_id")
    raw_name = item.get("name") or item.get("repo_name")
    if not isinstance(raw_id, str) or not raw_id.strip():
        return None
    if not isinstance(raw_name, str) or not raw_name.strip():
        return None

    raw_owner = item.get("owner")
    owner = (
        raw_owner.strip() if isinstance(raw_owner, str) and raw_owner.strip() else None
    )
    return SeafileLibrary(id=raw_id.strip(), name=raw_name.strip(), owner=owner)


def list_libraries_from_seafile(base_url: str, api_token: str) -> list[SeafileLibrary]:
    normalized_base_url = normalize_seafile_base_url(base_url)

    try:
        response = request_with_retries(
            method="GET",
            url=f"{normalized_base_url}/api2/repos/",
            headers={"Authorization": f"Token {api_token}"},
        )
    except (requests.HTTPError, requests.RequestException) as exc:
        response = getattr(exc, "response", None)
        status_code = response.status_code if response is not None else None

        if status_code == 401:
            raise CredentialExpiredError(
                "Seafile API token is invalid or expired."
            ) from exc
        if status_code == 403:
            raise InsufficientPermissionsError(
                "Seafile API token cannot list readable libraries."
            ) from exc
        if status_code is not None and status_code >= 500:
            raise SeafileLibraryListingError(
                "Seafile returned a server error while listing libraries.",
                status_code=status_code,
            ) from exc

        raise SeafileLibraryListingError("Unable to list Seafile libraries.") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise SeafileLibraryListingError(
            "Seafile returned malformed JSON while listing libraries."
        ) from exc

    if not isinstance(data, list):
        raise SeafileLibraryListingError(
            "Seafile returned an unexpected library list response."
        )

    return [
        library
        for item in data
        if isinstance(item, dict)
        if (library := _extract_seafile_library(item)) is not None
    ]
