"""OAuth provider registry.

Adding a provider: create `<name>.py` with an `OAuth` subclass (plus
`StandardFlatRefresh` or a custom `Refresh` if it supports refresh),
add an `ExternalAppType` enum value, and append the class to
`_PROVIDER_CLASSES`.
"""

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import OAuth
from onyx.external_apps.providers.base import Refresh
from onyx.external_apps.providers.base import StandardFlatRefresh
from onyx.external_apps.providers.google_calendar import GoogleCalendarOAuth
from onyx.external_apps.providers.linear import LinearOAuth
from onyx.external_apps.providers.slack import SlackOAuth

_PROVIDER_CLASSES: list[type[OAuth]] = [
    SlackOAuth,
    GoogleCalendarOAuth,
    LinearOAuth,
]

PROVIDERS: dict[ExternalAppType, OAuth] = {
    cls.app_type: cls() for cls in _PROVIDER_CLASSES
}


def get_provider_for_app(app: ExternalApp) -> OAuth | None:
    return PROVIDERS.get(app.app_type)


def get_provider_or_raise(app: ExternalApp) -> OAuth:
    provider = PROVIDERS.get(app.app_type)
    if provider is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"OAuth flow not configured for app '{app.name}' "
            f"(app_type={app.app_type}).",
        )
    return provider


__all__ = [
    "OAuth",
    "Refresh",
    "StandardFlatRefresh",
    "SlackOAuth",
    "GoogleCalendarOAuth",
    "LinearOAuth",
    "PROVIDERS",
    "get_provider_for_app",
    "get_provider_or_raise",
]
