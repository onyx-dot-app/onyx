from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.external_apps.models import (
    BuiltInExternalAppDescriptor,
    EndpointDescriptor,
    OrgCredentialFieldDescriptor,
)
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.external_apps.providers.base import ExternalAppProvider, OnyxManagedExtApp
from onyx.external_apps.providers.github import GitHubProvider
from onyx.external_apps.providers.gmail import GmailProvider
from onyx.external_apps.providers.google_calendar import GoogleCalendarProvider
from onyx.external_apps.providers.google_drive import GoogleDriveProvider
from onyx.external_apps.providers.hubspot import HubspotProvider
from onyx.external_apps.providers.linear import LinearProvider
from onyx.external_apps.providers.notion import NotionProvider
from onyx.external_apps.providers.slack import SlackProvider
from onyx.external_apps.providers.zendesk import ZendeskProvider
from shared_configs.configs import MULTI_TENANT

_PROVIDER_CLASSES: list[type[ExternalAppProvider]] = [
    SlackProvider,
    GoogleCalendarProvider,
    GoogleDriveProvider,
    GmailProvider,
    LinearProvider,
    GitHubProvider,
    HubspotProvider,
    NotionProvider,
    ZendeskProvider,
]


def _build_providers() -> dict[ExternalAppType, ExternalAppProvider]:
    providers: dict[ExternalAppType, ExternalAppProvider] = {}
    for cls in _PROVIDER_CLASSES:
        app_type = cls.spec.app_type
        if app_type in providers:
            existing = type(providers[app_type]).__name__
            raise RuntimeError(
                f"Duplicate provider registration for "
                f"app_type={app_type}: {existing} and {cls.__name__}."
            )
        providers[app_type] = cls()
    return providers


PROVIDERS: dict[ExternalAppType, ExternalAppProvider] = _build_providers()


def get_provider_for_app(app: ExternalApp) -> ExternalAppProvider | None:
    return PROVIDERS.get(app.app_type)


def get_onyx_managed_provider(app_type: ExternalAppType) -> OnyxManagedExtApp | None:
    """The Onyx-managed provider for ``app_type``, or None when the app_type is
    CUSTOM/unregistered or its provider isn't Onyx-managed. Not gated on
    ``MULTI_TENANT`` — callers add that for the cloud-only lockdown (``is not
    None`` is the "is this app Onyx-managed" check)."""
    provider = PROVIDERS.get(app_type)
    return provider if isinstance(provider, OnyxManagedExtApp) else None


def uses_cloud_scope(app_type: ExternalAppType) -> bool:
    """Whether this app connects with Onyx's cloud OAuth client rather than
    credentials the deployment owns. That client is verified with the upstream
    provider, so providers narrow their scope there (see ``GoogleOAuthProvider``)
    and the actions it can't cover drop out of the catalog."""
    return MULTI_TENANT and get_onyx_managed_provider(app_type) is not None


def _descriptor_for(
    provider_cls: type[ExternalAppProvider],
) -> BuiltInExternalAppDescriptor:
    spec = provider_cls.spec
    descriptor = spec.descriptor
    return BuiltInExternalAppDescriptor(
        app_type=spec.app_type,
        name=spec.app_name,
        upstream_url_patterns=list(descriptor.upstream_url_patterns),
        auth_template=dict(descriptor.auth_template),
        required_org_credential_fields=[
            OrgCredentialFieldDescriptor(
                key=f.key,
                label=f.label,
                description=f.description,
                secret=f.secret,
            )
            for f in descriptor.required_org_credential_fields
        ],
        setup_instructions=descriptor.setup_instructions,
        actions=[
            EndpointDescriptor(
                action_id=e.id,
                normalised_name=e.normalised_name,
                description=e.description,
                default_policy=e.default_policy,
            )
            for e in get_endpoint_catalog(spec.app_type)
        ],
    )


def get_endpoint_catalog(app_type: ExternalAppType) -> list[EndpointSpec]:
    """The action catalog for an app_type (empty for CUSTOM / unregistered),
    minus the actions the OAuth grant in force can't cover. Every consumer
    (admin view, policy resolution, the runtime gate) funnels through here, so
    none of them can offer an action the grant won't authorize."""
    provider = PROVIDERS.get(app_type)
    if provider is None:
        return []
    catalog = provider.spec.endpoint_catalog
    if uses_cloud_scope(app_type):
        return [e for e in catalog if not e.requires_self_hosted_scope]
    return list(catalog)


def withheld_on_cloud(app_type: ExternalAppType) -> list[EndpointSpec]:
    """The catalog actions this app cannot offer on cloud, where Onyx's own
    OAuth client must avoid Google's restricted scopes — every endpoint marked
    ``requires_self_hosted_scope``. Empty when the deployment uses its own
    credentials."""
    if not uses_cloud_scope(app_type):
        return []
    # uses_cloud_scope implies the provider is registered.
    catalog = PROVIDERS[app_type].spec.endpoint_catalog
    return [e for e in catalog if e.requires_self_hosted_scope]


def fetch_onyx_managed_built_in_apps() -> list[BuiltInExternalAppDescriptor]:
    """Built-in providers Onyx owns the credentials for — the apps cloud
    provisioning seeds per tenant. Excludes non-managed built-ins."""
    return [
        _descriptor_for(cls)
        for cls in _PROVIDER_CLASSES
        if issubclass(cls, OnyxManagedExtApp)
    ]
