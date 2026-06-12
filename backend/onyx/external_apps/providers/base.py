from abc import ABC
from collections.abc import Mapping
from typing import Any
from typing import ClassVar

from pydantic import BaseModel
from pydantic import ConfigDict

from onyx.db.enums import ExternalAppType
from onyx.external_apps.oauth_handler import OAuthFlowHandler
from onyx.external_apps.oauth_handler import OAuthFlowSpec
from onyx.external_apps.presentation.payload_decoders import PayloadDecoder
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.utils.logger import setup_logger

logger = setup_logger()


class OrgCredentialField(BaseModel):
    """One credential field the admin must fill in when configuring a
    built-in provider (e.g. OAuth client_id, client_secret)."""

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    description: str
    secret: bool = False


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


class OAuthExternalAppProvider(ExternalAppProvider, OAuthFlowHandler, abstract=True):
    """An :class:`ExternalAppProvider` that is also an :class:`OAuthFlowHandler`,
    sourcing flow parameters from ``spec.oauth``. Subclasses supply an
    :class:`OAuthProviderSpec` and implement :meth:`extract_credentials`;
    divergent providers override a handler hook, not the POST flow."""

    spec: ClassVar[OAuthProviderSpec]
    _spec_type: ClassVar[type[ProviderSpec]] = OAuthProviderSpec

    @property
    def oauth(self) -> OAuthFlowSpec:
        return self.spec.oauth
