"""Minimal stub of the generated OpenAPI client for type checking.

This is intentionally tiny and only includes the attributes and methods
referenced by integration test helpers. The real client is generated at
build time and may override this module.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any
from typing import Optional


class Configuration:
    def __init__(self, host: Optional[str] = None) -> None:
        self.host = host or ""


class ApiClient(AbstractContextManager["ApiClient"]):
    def __init__(self, configuration: Optional[Configuration] = None) -> None:
        self.configuration = configuration or Configuration()

    # Context manager support
    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None


class StatusResponseInt:
    def __init__(self, data: int) -> None:
        self.data = data


class ConnectorCredentialPairMetadata:
    def __init__(
        self,
        name: str,
        access_type: Any,
        groups: list[int] | None = None,
    ) -> None:
        self.name = name
        self.access_type = access_type
        self.groups = groups or []


class DefaultApi:
    def __init__(self, api_client: ApiClient) -> None:  # noqa: D401
        self._client = api_client

    # Only the method signature used in tests is provided here.
    def associate_credential_to_connector(
        self,
        connector_id: int,
        credential_id: int,
        connector_credential_pair_metadata: ConnectorCredentialPairMetadata,
        _headers: Optional[dict[str, Any]] = None,
    ) -> StatusResponseInt:
        # Return a dummy response adequate for type checking.
        return StatusResponseInt(0)
