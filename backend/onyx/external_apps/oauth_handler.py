"""The OAuth 2.0 mechanics seam shared by built-in providers and admin-defined
custom apps: authorize-URL construction, the authorization-code exchange, and
token refresh, with both grants going through one token-request helper.
Built-in providers implement it via ``OAuthExternalAppProvider``; CUSTOM apps
use the config-driven ``CustomOAuthHandler``. Resolution from an
``ExternalApp`` row lives in ``providers.registry.resolve_oauth_handler``.
"""

import base64
from abc import ABC
from abc import abstractmethod
from enum import Enum
from typing import Any
from typing import ClassVar
from urllib.parse import urlencode

import requests
from pydantic import BaseModel
from pydantic import ConfigDict


class TokenRequestError(Exception):
    """Base class for OAuth token-endpoint failures (initial grant or refresh)."""


class TokenRequestTerminalError(TokenRequestError):
    """The grant itself is dead (revoked / invalid_grant / missing). On a
    refresh, the stored credential should be cleared and the user prompted to
    reconnect — retrying cannot succeed."""


class TokenRequestTransientError(TokenRequestError):
    """A transient failure (network, 5xx, non-JSON, rate-limit). On a refresh,
    the existing token should be left in place and retried on a later request."""


def token_response_error(http_response: requests.Response, body: Any) -> str | None:
    """Slack returns 200 + ``{"ok": false}`` on failure; everyone else uses
    non-2xx. Returns the error string or ``None`` on success.

    ``body`` is whatever ``response.json()`` produced, so it may not be a JSON
    object (a gateway can return a bare array / string / number / ``null``). A
    non-object can't carry an OAuth error code, so a non-2xx is reported as a
    generic failure and a 2xx falls through to credential mapping — never an
    unguarded ``.get()`` that would escape the token-request error handling."""
    if not isinstance(body, dict):
        if http_response.status_code >= 400:
            return f"unexpected token response (status={http_response.status_code})"
        return None
    if http_response.status_code >= 400:
        # Prefer the machine-readable `error` code over the human-readable
        # `error_description`: terminal-vs-transient classification matches against
        # OAuth error codes (e.g. `invalid_grant`), so returning the prose would
        # misclassify a dead grant as transient and skip required reconnect handling.
        return body.get("error") or body.get("error_description") or "unknown"
    if body.get("ok") is False:
        return body.get("error") or "unknown"
    return None


class TokenEndpointAuthMethod(str, Enum):
    """How the client authenticates to the token endpoint (RFC 6749 §2.3.1):
    credentials in the form body, or an HTTP Basic ``Authorization`` header."""

    CLIENT_SECRET_POST = "client_secret_post"
    CLIENT_SECRET_BASIC = "client_secret_basic"


class OAuthFlowSpec(BaseModel):
    """Initial-grant OAuth 2.0 parameters for an app. Consumed by
    :class:`OAuthFlowHandler` to build the authorize URL and exchange the
    code for a token."""

    model_config = ConfigDict(frozen=True)

    authorize_url: str
    token_url: str
    scope: str
    # The query param the `scope` value rides under. Slack uses `user_scope`
    # to request user-acting tokens; without it Slack assumes bot scopes.
    scope_param: str
    extra_authorize_params: dict[str, str] = {}


class OAuthFlowHandler(ABC):
    """OAuth mechanics for one app: the authorize URL, the authorization-code
    exchange, and token refresh.

    Both grants go through :meth:`_post_token_request`, so a divergent app
    overrides a hook (:meth:`extract_credentials`, :meth:`build_refresh_request`,
    :meth:`classify_token_response`) or an attribute below — never the
    POST/error-handling flow itself.
    """

    # Bounded so a slow token endpoint can't pin the caller (and the gate).
    token_http_timeout_seconds: ClassVar[float] = 20.0

    # Error codes meaning the grant itself is dead, so the user must reconnect
    # (RFC 6749 §5.2).
    terminal_token_errors: ClassVar[frozenset[str]] = frozenset({"invalid_grant"})

    # Plain attribute (not ClassVar) so a config-driven handler can set it
    # per instance.
    token_endpoint_auth_method: TokenEndpointAuthMethod = (
        TokenEndpointAuthMethod.CLIENT_SECRET_POST
    )

    @property
    @abstractmethod
    def oauth(self) -> OAuthFlowSpec:
        """The flow parameters (authorize/token URLs, scope, authorize params)."""

    @abstractmethod
    def extract_credentials(self, response_data: dict[str, Any]) -> dict[str, Any]:
        """Map a successful token response (initial grant *or* refresh) to the
        credentials to persist for the user (e.g. pull the user access token out
        of Slack's nested ``authed_user``). Raise ``OnyxError`` if the expected
        token is absent."""

    def build_authorize_url(
        self, *, client_id: str, redirect_uri: str, state: str
    ) -> str:
        """The provider authorize URL the user's browser is sent to
        (RFC 6749 §4.1.1)."""
        oauth = self.oauth
        params: dict[str, str] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
        }
        # An empty scope omits the param entirely (provider-default scopes).
        if oauth.scope:
            params[oauth.scope_param] = oauth.scope
        params["state"] = state
        params.update(oauth.extra_authorize_params)
        # urlencode so URI-shaped scopes (Google) get `:` and `/`
        # percent-encoded.
        return f"{oauth.authorize_url}?{urlencode(params)}"

    def exchange_authorization_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        client_id: str,
        client_secret: str,
    ) -> dict[str, Any]:
        """The initial authorization-code grant (RFC 6749 §4.1.3): exchange the
        code and map the response via :meth:`extract_credentials`.

        Raises :class:`TokenRequestError` for transport/provider failures (the
        caller maps it to its own error vocabulary); :meth:`extract_credentials`
        may raise ``OnyxError`` for an unmappable success response.
        """
        body = self._post_token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            client_id=client_id,
            client_secret=client_secret,
        )
        return self.extract_credentials(body)

    def refresh_credentials(
        self,
        stored: dict[str, Any],
        client_id: str,
        client_secret: str,
    ) -> dict[str, Any]:
        """Exchange the stored refresh token for a fresh access token (RFC 6749
        §6). Clockless (the caller stamps ``expires_at``), mirroring
        :meth:`extract_credentials`.

        Raises:
            TokenRequestTerminalError: the grant is dead (reconnect required).
            TokenRequestTransientError: a retryable failure (network / 5xx / …).
        """
        refresh_token = stored.get("refresh_token")
        if not refresh_token:
            raise TokenRequestTerminalError(
                "No refresh token stored; the user must reconnect."
            )

        body = self._post_token_request(
            self.build_refresh_request(refresh_token),
            client_id=client_id,
            client_secret=client_secret,
        )
        try:
            mapped = self.extract_credentials(body)
        except TokenRequestError:
            raise
        except Exception as exc:
            # A 2xx body we can't map (unexpected shape) isn't a dead grant —
            # transient, so the caller keeps the existing token, not clears it.
            # Keeps this method's contract: it raises only TokenRequestError.
            raise TokenRequestTransientError(
                f"could not map refresh response: {exc}"
            ) from exc

        # Merge onto the stored creds (response wins) rather than replace, so
        # connect-time-only fields (Slack's team_id, a prior id_token, …) and the
        # refresh token survive a refresh that returns only the rotated subset.
        return {**stored, **mapped}

    def build_refresh_request(self, refresh_token: str) -> dict[str, str]:
        """The refresh POST form body, sans client auth (applied centrally by
        :meth:`_post_token_request`). Override to add provider-specific params
        (scope, resource, audience, …) or change the grant."""
        return {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

    def classify_token_response(
        self, response: requests.Response, body: dict[str, Any]
    ) -> str | None:
        """Error code from a token response, or ``None`` on success. Override for
        apps whose failure signalling isn't covered by
        :func:`token_response_error`."""
        return token_response_error(response, body)

    def _post_token_request(
        self,
        data: dict[str, str],
        *,
        client_id: str,
        client_secret: str,
    ) -> dict[str, Any]:
        """POST ``data`` to the token endpoint with client auth applied per
        ``token_endpoint_auth_method``; parse and classify the response. The
        single transport path for both grants.

        Returns the parsed JSON object. Raises :class:`TokenRequestTerminalError`
        for dead-grant error codes, :class:`TokenRequestTransientError` for
        everything else (network, non-JSON, non-object body, other error codes).
        """
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            # Ask for JSON so providers that default to form-encoded token
            # responses (e.g. GitHub) still parse via response.json().
            "Accept": "application/json",
        }
        form = dict(data)
        if (
            self.token_endpoint_auth_method
            is TokenEndpointAuthMethod.CLIENT_SECRET_BASIC
        ):
            basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode(
                "ascii"
            )
            headers["Authorization"] = f"Basic {basic}"
        else:
            form["client_id"] = client_id
            form["client_secret"] = client_secret

        try:
            response = requests.post(
                self.oauth.token_url,
                headers=headers,
                data=form,
                timeout=self.token_http_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise TokenRequestTransientError(f"network error: {exc}") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise TokenRequestTransientError(
                f"non-JSON token response (status={response.status_code})"
            ) from exc

        error = self.classify_token_response(response, body)
        if error is not None:
            if error in self.terminal_token_errors:
                raise TokenRequestTerminalError(error)
            raise TokenRequestTransientError(error)
        if not isinstance(body, dict):
            # A 2xx non-object body can't be a token response; surface it as
            # transient rather than letting credential mapping crash on it.
            raise TokenRequestTransientError(
                f"unexpected token response (status={response.status_code})"
            )
        return body
