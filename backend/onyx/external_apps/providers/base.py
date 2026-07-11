from abc import ABC
from abc import abstractmethod
from collections.abc import Mapping
from typing import Any
from typing import ClassVar

import requests
from pydantic import BaseModel
from pydantic import ConfigDict

from onyx.db.enums import ExternalAppType
from onyx.external_apps.presentation.payload_decoders import PayloadDecoder
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.utils.logger import setup_logger

logger = setup_logger()


class TokenRefreshError(Exception):
    """Base class for OAuth access-token refresh failures."""


class TokenRefreshTerminalError(TokenRefreshError):
    """The refresh token is dead (revoked / invalid_grant / missing). The stored
    credential should be cleared and the user prompted to reconnect — retrying
    cannot succeed."""


class TokenRefreshTransientError(TokenRefreshError):
    """A transient failure (network, 5xx, non-JSON, rate-limit). The existing
    token should be left in place and the refresh retried on a later request."""


def token_response_error(http_response: requests.Response, body: Any) -> str | None:
    """Slack returns 200 + ``{"ok": false}`` on failure; everyone else uses
    non-2xx. Returns the error string or ``None`` on success.

    ``body`` is whatever ``response.json()`` produced, so it may not be a JSON
    object (a gateway can return a bare array / string / number / ``null``). A
    non-object can't carry an OAuth error code, so a non-2xx is reported as a
    generic failure and a 2xx falls through to credential mapping — never an
    unguarded ``.get()`` that would escape the refresh error handling."""
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


def parse_granted_scopes(raw: object) -> list[str] | None:
    """Normalise a granted-scope signal (delimited string or list) into a scope
    list. Returns ``None`` — never ``[]`` — for an absent/empty signal, so
    callers record "grant unknown" rather than an (impossible) empty grant.
    """
    if isinstance(raw, str):
        # Space- or comma-delimited (RFC 6749 §3.3; GitHub/Slack), incl. mixed
        # forms like "repo, gist" — normalise to spaces so split() handles all.
        parts: list[str] = raw.replace(",", " ").split()
    elif isinstance(raw, list):
        parts = [str(scope) for scope in raw]
    else:
        return None
    scopes = [stripped for part in parts if (stripped := part.strip())]
    return scopes or None


class OrgCredentialField(BaseModel):
    """One credential field the admin must fill in when configuring a
    built-in provider (e.g. OAuth client_id, client_secret)."""

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    description: str
    secret: bool = False


class OAuthFlowSpec(BaseModel):
    """Initial-grant OAuth 2.0 parameters for a provider. Consumed by the
    External-App OAuth routes to build the authorize URL and exchange the
    code for a token."""

    model_config = ConfigDict(frozen=True)

    authorize_url: str
    token_url: str
    scope: str
    # The query param the `scope` value rides under. Slack uses `user_scope`
    # to request user-acting tokens; without it Slack assumes bot scopes.
    scope_param: str
    # Space-joined scopes requested as optional. Providers that honor them
    # (e.g. HubSpot) drop any the account can't grant rather than failing the
    # whole authorize page, so writes don't lock out read-only tiers. Empty
    # means the param is omitted.
    optional_scope: str = ""
    # The query param `optional_scope` rides under, mirroring `scope_param`.
    optional_scope_param: str = "optional_scope"
    extra_authorize_params: dict[str, str] = {}


class AdminDescriptorSpec(BaseModel):
    """Everything the admin Configure modal renders and the egress gateway
    needs. Surfaced verbatim through ``BuiltInExternalAppDescriptor`` so the
    frontend can render the modal without knowing any provider specifics."""

    model_config = ConfigDict(frozen=True)

    description: str
    upstream_url_patterns: list[str]
    auth_template: dict[str, str]
    required_org_credential_fields: list[OrgCredentialField]
    setup_instructions: str


class ProviderSpec(BaseModel):
    """The base declarative definition every built-in provider must supply:
    identity, the admin descriptor, and the action catalog. Pydantic enforces
    that nothing is missing. OAuth providers use the :class:`OAuthProviderSpec`
    subtype, which additionally carries the flow."""

    model_config = ConfigDict(frozen=True)

    app_type: ExternalAppType
    app_name: str
    descriptor: AdminDescriptorSpec
    # The actions an admin can govern. Empty for a provider with no catalog yet.
    endpoint_catalog: list[EndpointSpec] = []


class OAuthProviderSpec(ProviderSpec):
    """A :class:`ProviderSpec` for providers whose users authenticate via an
    OAuth 2.0 flow. Paired with :class:`OAuthExternalAppProvider`."""

    oauth: OAuthFlowSpec


class TokenExchangeRequest(BaseModel):
    """The authorization-code token-exchange POST, built by the provider so a
    divergent provider can override how client credentials and the grant ride
    on the request. The default is RFC-6749 form-encoded creds in the body;
    Notion, for example, needs HTTP Basic client auth plus a JSON body. The
    OAuth callback route consumes this without knowing any provider specifics.
    """

    model_config = ConfigDict(frozen=True)

    headers: dict[str, str]
    body: dict[str, str]
    # How ``body`` is encoded on the wire: JSON (``requests.post(json=...)``)
    # when True, RFC-6749 form-encoded (``data=...``) when False. The callback
    # route maps this to exactly one of `data`/`json` so `requests` never sees
    # both (which would silently drop the form body in favour of JSON).
    json_encoded: bool = False


class ExternalAppProvider(ABC):
    """Base contract for a built-in external-app provider.

    Every provider MUST define ``spec`` (a :class:`ProviderSpec`), validated at
    class-definition time. Providers that authenticate via OAuth subclass
    :class:`OAuthExternalAppProvider` instead, which narrows ``spec`` to
    :class:`OAuthProviderSpec` and adds the credential-extraction hook.

    Abstract tiers in this hierarchy pass ``abstract=True`` so they're exempt
    from the ``spec`` requirement; only concrete, registrable providers are
    checked."""

    spec: ClassVar[ProviderSpec]

    # The spec subtype this tier requires. Overridden by OAuth providers.
    _spec_type: ClassVar[type[ProviderSpec]] = ProviderSpec

    def __init_subclass__(cls, *, abstract: bool = False, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if abstract:
            return
        spec = cls.__dict__.get("spec")
        if not isinstance(spec, cls._spec_type):
            raise TypeError(
                f"{cls.__name__} must define `spec` as a "
                f"{cls._spec_type.__name__} instance."
            )

    def payload_decoders(self) -> Mapping[str, PayloadDecoder]:
        """Display decoders for this provider's request bodies, keyed by
        ``action_type``. Empty by default; override to register decoders."""
        return {}


class OnyxManagedExtApp(ExternalAppProvider, abstract=True):
    """Interface for a built-in provider whose OAuth client credentials Onyx
    owns. On managed cloud these are seeded per tenant and locked down (admins
    may only enable/disable + set policies — never edit credentials/config or
    delete). A non-managed built-in (admin/user-configurable) simply doesn't
    inherit this, so it carries no Onyx-owned credentials and stays editable.

    A concrete managed provider declares its operator-supplied credentials in
    ``managed_org_credentials``, keyed by the same fields as its
    ``required_org_credential_fields`` (validated in ``__init_subclass__``).
    """

    # Onyx-owned credential values, sourced from the ``EXT_APP_<APP_TYPE>_<FIELD>``
    # constants in ``app_configs``. Keys must match the spec's required fields.
    managed_org_credentials: ClassVar[dict[str, str]] = {}

    def __init_subclass__(cls, *, abstract: bool = False, **kwargs: Any) -> None:
        # Forward ``abstract`` so the base still validates ``spec`` first (and
        # skips abstract tiers); only then check our credential mapping.
        super().__init_subclass__(abstract=abstract, **kwargs)
        if abstract:
            return
        # A managed provider must map exactly its required credential fields, so
        # provisioning seeds the right keys (values may be blank when the
        # deployment hasn't configured them yet).
        required = {f.key for f in cls.spec.descriptor.required_org_credential_fields}
        configured = set(cls.managed_org_credentials)
        if configured != required:
            raise TypeError(
                f"{cls.__name__} is an OnyxManagedExtApp but its "
                f"managed_org_credentials keys {sorted(configured)} do not "
                f"match its required credential fields {sorted(required)}."
            )

    def configured_managed_credentials(self) -> dict[str, str] | None:
        """This provider's Onyx-owned credentials if fully configured, else None."""
        creds = {k: v.strip() for k, v in self.managed_org_credentials.items()}
        if not any(creds.values()):
            return None  # nothing configured
        if all(creds.values()):
            return creds
        # partially set — almost always a config mistake worth surfacing
        missing = ", ".join(
            f"EXT_APP_{self.spec.app_type.value}_{k.upper()}"
            for k, v in creds.items()
            if not v
        )
        logger.warning(
            "Incomplete managed credentials for built-in app '%s'; missing %s. "
            "Treating as unconfigured.",
            self.spec.app_type.value,
            missing,
        )
        return None


class OAuthExternalAppProvider(ExternalAppProvider, abstract=True):
    """A provider whose users authenticate via OAuth 2.0. Subclasses supply an
    :class:`OAuthProviderSpec` and implement :meth:`extract_credentials`.

    :meth:`refresh_credentials` is a template method: a divergent provider
    overrides one hook (`build_refresh_request`, `classify_token_response`) or
    class property below, not the whole POST/error-handling flow.
    """

    spec: ClassVar[OAuthProviderSpec]
    _spec_type: ClassVar[type[ProviderSpec]] = OAuthProviderSpec

    # --- Refresh configuration (override per provider as needed) ---

    # Bounded so a slow token endpoint can't pin the refresh (and the gate).
    refresh_http_timeout_seconds: ClassVar[float] = 20.0

    # Error codes meaning the grant itself is dead, so the user must reconnect
    # (RFC 6749 §5.2).
    terminal_refresh_errors: ClassVar[frozenset[str]] = frozenset({"invalid_grant"})

    @abstractmethod
    def extract_credentials(self, response_data: dict[str, Any]) -> dict[str, Any]:
        """Map a successful token response (initial grant *or* refresh) to the
        credentials to persist for the user (e.g. pull the user access token out
        of Slack's nested ``authed_user``). Raise ``OnyxError`` if the expected
        token is absent."""

    def extract_granted_scopes(self, response_data: dict[str, Any]) -> list[str] | None:
        """The scopes the user granted, from the connect-time token response, or
        ``None`` when the provider gives no authoritative signal.

        Default reads the RFC 6749 §3.3 ``scope`` field. Override for providers
        that nest it (Slack) or require a separate lookup (HubSpot).
        """
        return parse_granted_scopes(response_data.get("scope"))

    # --- Initial-grant token exchange (override for divergent client auth) ---

    def build_token_exchange_request(
        self, code: str, client_id: str, client_secret: str, redirect_uri: str
    ) -> TokenExchangeRequest:
        """Build the authorization-code → token exchange POST. The default sends
        RFC-6749 form-encoded client credentials in the body. Override for a
        provider that requires HTTP Basic client auth and/or a JSON body (e.g.
        Notion)."""
        return TokenExchangeRequest(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            body={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )

    # --- Refresh template method (override a hook below, not this) ---

    def refresh_credentials(
        self,
        stored: dict[str, Any],
        client_id: str,
        client_secret: str,
    ) -> dict[str, Any]:
        """Exchange the stored refresh token for a fresh access token (RFC-6749).

        Clockless (the caller stamps ``expires_at``), mirroring
        :meth:`extract_credentials`. Override `build_refresh_request` /
        `classify_token_response` for a divergent provider.

        Raises:
            TokenRefreshTerminalError: the grant is dead (reconnect required).
            TokenRefreshTransientError: a retryable failure (network / 5xx / …).
        """
        refresh_token = stored.get("refresh_token")
        if not refresh_token:
            raise TokenRefreshTerminalError(
                "No refresh token stored; the user must reconnect."
            )

        try:
            response = requests.post(
                self.spec.oauth.token_url,
                # Ask for JSON so providers that default to form-encoded
                # refresh responses (e.g. GitHub) still parse via response.json().
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data=self.build_refresh_request(
                    refresh_token, client_id, client_secret
                ),
                timeout=self.refresh_http_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise TokenRefreshTransientError(f"network error: {exc}") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise TokenRefreshTransientError(
                f"non-JSON token response (status={response.status_code})"
            ) from exc

        error = self.classify_token_response(response, body)
        if error is not None:
            if error in self.terminal_refresh_errors:
                raise TokenRefreshTerminalError(error)
            raise TokenRefreshTransientError(error)

        try:
            mapped = self.extract_credentials(body)
        except TokenRefreshError:
            raise
        except Exception as exc:
            # A 2xx body we can't map (unexpected shape) isn't a dead grant —
            # transient, so the caller keeps the existing token, not clears it.
            # Keeps this method's contract: it raises only TokenRefreshError.
            raise TokenRefreshTransientError(
                f"could not map refresh response: {exc}"
            ) from exc

        # Merge onto the stored creds (response wins) rather than replace, so
        # connect-time-only fields (Slack's team_id, a prior id_token, …) and the
        # refresh token survive a refresh that returns only the rotated subset.
        return {**stored, **mapped}

    def build_refresh_request(
        self, refresh_token: str, client_id: str, client_secret: str
    ) -> dict[str, str]:
        """The refresh POST form body. Override to add provider-specific params
        (scope, resource, audience, …) or change the grant."""
        return {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }

    def classify_token_response(
        self, response: requests.Response, body: dict[str, Any]
    ) -> str | None:
        """Error code from a token response, or ``None`` on success. Override for
        providers whose failure signalling isn't covered by
        :func:`token_response_error`."""
        return token_response_error(response, body)
