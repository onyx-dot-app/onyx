from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import OAuth
from onyx.external_apps.providers.base import OrgCredentialField
from onyx.external_apps.providers.google_calendar import GoogleCalendarOAuth
from onyx.external_apps.providers.linear import LinearOAuth
from onyx.external_apps.providers.slack import SlackOAuth
from onyx.server.features.build.api.models import BuiltInExternalAppDescriptor
from onyx.server.features.build.api.models import OrgCredentialFieldDescriptor

_PROVIDER_CLASSES: list[type[OAuth]] = [
    SlackOAuth,
    GoogleCalendarOAuth,
    LinearOAuth,
]


def _build_providers() -> dict[ExternalAppType, OAuth]:
    providers: dict[ExternalAppType, OAuth] = {}
    for cls in _PROVIDER_CLASSES:
        if cls.app_type in providers:
            existing = type(providers[cls.app_type]).__name__
            raise RuntimeError(
                f"Duplicate OAuth provider registration for "
                f"app_type={cls.app_type}: {existing} and {cls.__name__}."
            )
        providers[cls.app_type] = cls()
    return providers


PROVIDERS: dict[ExternalAppType, OAuth] = _build_providers()


def get_provider_for_app(app: ExternalApp) -> OAuth | None:
    return PROVIDERS.get(app.app_type)


def get_provider_or_raise(app: ExternalApp) -> OAuth:
    provider = get_provider_for_app(app)
    if provider is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"OAuth flow not configured for app '{app.skill.name}' "
            f"(app_type={app.app_type}).",
        )
    return provider


def _descriptor_for(provider_cls: type[OAuth]) -> BuiltInExternalAppDescriptor:
    return BuiltInExternalAppDescriptor(
        app_type=provider_cls.app_type,
        name=provider_cls.app_name,
        description=provider_cls.description,
        upstream_url_patterns=list(provider_cls.upstream_url_patterns),
        auth_template=dict(provider_cls.auth_template),
        required_org_credential_fields=[
            _to_credential_field_descriptor(f)
            for f in provider_cls.required_org_credential_fields
        ],
        setup_instructions=provider_cls.setup_instructions,
    )


def _to_credential_field_descriptor(
    field: OrgCredentialField,
) -> OrgCredentialFieldDescriptor:
    return OrgCredentialFieldDescriptor(
        key=field.key,
        label=field.label,
        description=field.description,
        secret=field.secret,
    )


def fetch_available_built_in_apps() -> list[BuiltInExternalAppDescriptor]:
    """All registered built-in providers as Pydantic descriptors. The
    admin UI fetches this list to render the Manage Apps page."""
    return [_descriptor_for(cls) for cls in _PROVIDER_CLASSES]


def fetch_built_in_app(app_type: ExternalAppType) -> BuiltInExternalAppDescriptor:
    for cls in _PROVIDER_CLASSES:
        if cls.app_type == app_type:
            return _descriptor_for(cls)
    raise OnyxError(
        OnyxErrorCode.NOT_FOUND,
        f"No built-in app for app_type={app_type}.",
    )


__all__ = [
    "OAuth",
    "SlackOAuth",
    "GoogleCalendarOAuth",
    "LinearOAuth",
    "PROVIDERS",
    "get_provider_for_app",
    "get_provider_or_raise",
    "fetch_available_built_in_apps",
    "fetch_built_in_app",
]
