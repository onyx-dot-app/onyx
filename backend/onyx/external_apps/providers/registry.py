from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.external_apps.providers.base import ExternalAppProvider
from onyx.external_apps.providers.base import OnyxManagedExtApp
from onyx.external_apps.providers.github import GitHubProvider
from onyx.external_apps.providers.gmail import GmailProvider
from onyx.external_apps.providers.google_calendar import GoogleCalendarProvider
from onyx.external_apps.providers.google_drive import GoogleDriveProvider
from onyx.external_apps.providers.linear import LinearProvider
from onyx.external_apps.providers.slack import SlackProvider
from onyx.server.features.build.api.models import ActionPolicyView
from onyx.server.features.build.api.models import BuiltInExternalAppDescriptor
from onyx.server.features.build.api.models import EndpointDescriptor
from onyx.server.features.build.api.models import OrgCredentialFieldDescriptor

_PROVIDER_CLASSES: list[type[ExternalAppProvider]] = [
    SlackProvider,
    GoogleCalendarProvider,
    GoogleDriveProvider,
    GmailProvider,
    LinearProvider,
    GitHubProvider,
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


def build_action_policies(
    app_type: ExternalAppType,
    requested: dict[str, EndpointPolicy] | None,
    existing: dict[str, EndpointPolicy],
) -> dict[str, EndpointPolicy]:
    """The complete policy set to persist for a built-in app: one entry per
    catalog action, so the stored rows are the full source of truth.

    Each action resolves to the admin's validated override if supplied, else the
    value already stored, else the action's ``default_policy`` (``ASK`` unless the
    provider declared otherwise). Unmentioned actions keep their stored choice — a
    partial update (or an enable toggle that omits the map) never clobbers existing
    policies. Raises if ``requested`` names an action id outside the catalog.
    """
    validated = validate_action_policies(app_type, requested or {})
    return {
        endpoint.id: validated.get(
            endpoint.id, existing.get(endpoint.id, endpoint.default_policy)
        )
        for endpoint in get_endpoint_catalog(app_type)
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
            state=stored.get(endpoint.id, endpoint.default_policy),
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


def fetch_built_in_app(app_type: ExternalAppType) -> BuiltInExternalAppDescriptor:
    for cls in _PROVIDER_CLASSES:
        if cls.spec.app_type == app_type:
            return _descriptor_for(cls)
    raise OnyxError(
        OnyxErrorCode.NOT_FOUND,
        f"No built-in app for app_type={app_type}.",
    )
