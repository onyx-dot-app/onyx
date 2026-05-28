from abc import ABC
from abc import abstractmethod
from typing import Any
from typing import ClassVar

from pydantic import BaseModel
from pydantic import ConfigDict

from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers.actions import EndpointSpec


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


class OAuthExternalAppProvider(ExternalAppProvider, abstract=True):
    """A provider whose users authenticate via an OAuth 2.0 flow. Concrete
    subclasses MUST supply an :class:`OAuthProviderSpec` (so ``spec.oauth`` is
    always present) and implement :meth:`extract_credentials`."""

    spec: ClassVar[OAuthProviderSpec]
    _spec_type: ClassVar[type[ProviderSpec]] = OAuthProviderSpec

    @abstractmethod
    def extract_credentials(self, response_data: dict[str, Any]) -> dict[str, Any]:
        """Map a successful token-exchange response to the credentials to
        persist for the user (e.g. pull the user access token out of Slack's
        nested ``authed_user``). Raise ``OnyxError`` if the expected token is
        absent."""
