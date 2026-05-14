"""Abstract interfaces for OAuth providers."""

from abc import ABC
from abc import abstractmethod
from typing import Any
from typing import ClassVar

from onyx.db.enums import ExternalAppType


class OAuth(ABC):
    """Initial-grant OAuth 2.0 flow."""

    app_type: ClassVar[ExternalAppType]
    app_name: ClassVar[str]
    authorize_url: ClassVar[str]
    token_url: ClassVar[str]
    scope: ClassVar[str]
    # Slack uses `user_scope` instead of `scope` to request user-acting
    # tokens; without this, Slack interprets the request as bot scopes.
    scope_param: ClassVar[str]
    extra_authorize_params: ClassVar[dict[str, str]] = {}

    @abstractmethod
    def extract_credentials(self, response_data: dict[str, Any]) -> dict[str, Any]: ...


class Refresh(ABC):
    """Refresh-token grant. Mixin onto `OAuth` when the provider
    issues refresh tokens; the refresh adapter checks
    `isinstance(provider, Refresh)` before attempting refresh."""

    @abstractmethod
    def extract_refresh_credentials(
        self, response_data: dict[str, Any]
    ) -> dict[str, Any]: ...


class StandardFlatRefresh(Refresh):
    """Refresh parser for providers with the OAuth 2.0 standard flat
    response shape (Google, Linear, Slack-on-refresh)."""

    def extract_refresh_credentials(
        self, response_data: dict[str, Any]
    ) -> dict[str, Any]:
        creds: dict[str, Any] = {}
        if response_data.get("access_token"):
            creds["access_token"] = response_data["access_token"]
        if response_data.get("expires_in"):
            creds["expires_in"] = response_data["expires_in"]
        # Only set when present — caller's merge preserves the
        # existing refresh_token for providers like Google that
        # don't rotate.
        if response_data.get("refresh_token"):
            creds["refresh_token"] = response_data["refresh_token"]
        if response_data.get("scope"):
            creds["scope"] = response_data["scope"]
        return creds
