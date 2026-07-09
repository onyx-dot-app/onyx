from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.models import ActionPolicyView
from onyx.external_apps.models import BuiltInExternalAppDescriptor
from onyx.external_apps.models import EndpointDescriptor
from onyx.external_apps.models import OrgCredentialFieldDescriptor
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.external_apps.providers.base import ExternalAppProvider
from onyx.external_apps.providers.base import OnyxManagedExtApp
from onyx.external_apps.providers.github import GitHubProvider
from onyx.external_apps.providers.gmail import GmailProvider
from onyx.external_apps.providers.google_calendar import GoogleCalendarProvider
from onyx.external_apps.providers.google_drive import GoogleDriveProvider
from onyx.external_apps.providers.hubspot import HubspotProvider
from onyx.external_apps.providers.linear import LinearProvider
from onyx.external_apps.providers.notion import NotionProvider
from onyx.external_apps.providers.slack import SlackProvider

_PROVIDER_CLASSES: list[type[ExternalAppProvider]] = [
    SlackProvider,
    GoogleCalendarProvider,
    GoogleDriveProvider,
    GmailProvider,
    LinearProvider,
    GitHubProvider,
    HubspotProvider,
    NotionProvider,
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


def get_provider_or_raise(app: ExternalApp) -> ExternalAppProvider:
    provider = get_provider_for_app(app)
    if provider is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"No provider configured for app '{app.skill.name}' "
            f"(app_type={app.app_type}).",
        )
    return provider


def _descriptor_for(
    provider_cls: type[ExternalAppProvider],
) -> BuiltInExternalAppDescriptor:
    spec = provider_cls.spec
    descriptor = spec.descriptor
    return BuiltInExternalAppDescriptor(
        app_type=spec.app_type,
        name=spec.app_name,
        description=descriptor.description,
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
            for e in spec.endpoint_catalog
        ],
    )


def get_endpoint_catalog(app_type: ExternalAppType) -> list[EndpointSpec]:
    """The action catalog for an app_type (empty for CUSTOM / unregistered)."""
    provider = PROVIDERS.get(app_type)
    return list(provider.spec.endpoint_catalog) if provider is not None else []


def effective_policy(
    endpoint: EndpointSpec,
    stored: dict[str, EndpointPolicy],
) -> EndpointPolicy:
    """Policy in force for ``endpoint``: the admin's stored override, else the
    catalog's curated default. Shared by the runtime gate (``recognize_actions``) and
    the FE view (``action_policy_views``) so they never diverge — notably during
    catalog drift, when a newly-shipped endpoint has no stored row yet."""
    return stored.get(endpoint.id, endpoint.default_policy)


def validate_action_policies(
    app_type: ExternalAppType,
    policies: dict[str, EndpointPolicy],
) -> dict[str, EndpointPolicy]:
    """Validate admin-submitted ``{action_id: policy}`` against the provider
    catalog: reject any id that doesn't exist for this ``app_type``. Returns the
    validated map unchanged."""
    valid_ids = {endpoint.id for endpoint in get_endpoint_catalog(app_type)}
    for action_id in policies:
        if action_id not in valid_ids:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Unknown action '{action_id}' for app type {app_type.value}.",
            )
    return policies


def resolve_action_overrides(
    app_type: ExternalAppType,
    requested: dict[str, EndpointPolicy] | None,
    existing: dict[str, EndpointPolicy],
) -> dict[str, EndpointPolicy]:
    """The per-action overrides to persist: the admin's validated picks merged
    over existing overrides, with any entry equal to the catalog default — or
    naming an endpoint no longer in the catalog — pruned out.

    Catalog defaults are never materialized into rows: an action with no row
    resolves to its ``default_policy`` at read time (``effective_policy``), so
    new or re-defaulted catalog endpoints propagate to every tenant with no
    migration. ``requested is None`` leaves existing overrides untouched (still
    re-pruned against the current catalog, so materialized rows self-heal on the
    next write). Raises if ``requested`` names an action id outside the catalog.
    """
    catalog_defaults: dict[str, EndpointPolicy] = {
        endpoint.id: endpoint.default_policy
        for endpoint in get_endpoint_catalog(app_type)
    }
    merged = dict(existing)
    if requested is not None:
        merged.update(validate_action_policies(app_type, requested))
    return {
        action_id: policy
        for action_id, policy in merged.items()
        if action_id in catalog_defaults and policy != catalog_defaults[action_id]
    }


def action_policy_views(
    app_type: ExternalAppType,
    stored: dict[str, EndpointPolicy],
) -> list[ActionPolicyView]:
    """Merge the catalog with the admin's stored overrides: each action's
    effective ``state`` is the override if present, else the action's
    ``default_policy``. Orphan stored ids (no longer in the catalog) are
    silently dropped."""
    return [
        ActionPolicyView(
            action_id=endpoint.id,
            normalised_name=endpoint.normalised_name,
            description=endpoint.description,
            state=effective_policy(endpoint, stored),
        )
        for endpoint in get_endpoint_catalog(app_type)
    ]


def fetch_available_built_in_apps() -> list[BuiltInExternalAppDescriptor]:
    """All registered built-in providers as Pydantic descriptors. The
    admin UI fetches this list to render the Manage Apps page."""
    return [_descriptor_for(cls) for cls in _PROVIDER_CLASSES]


def fetch_onyx_managed_built_in_apps() -> list[BuiltInExternalAppDescriptor]:
    """Built-in providers Onyx owns the credentials for — the apps cloud
    provisioning seeds per tenant. Excludes non-managed built-ins."""
    return [
        _descriptor_for(cls)
        for cls in _PROVIDER_CLASSES
        if issubclass(cls, OnyxManagedExtApp)
    ]
