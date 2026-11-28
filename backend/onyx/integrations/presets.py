"""The presets of the ``api`` kind: one for each built-in external app
provider. A preset fills in the URLs, the sign-in settings and the action
catalog of an app. Presets stay in code."""

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers.registry import PROVIDERS
from onyx.integrations.models import Preset

# The redirect URI admins registered with each service before the integration
# tables. Keep it, so no OAuth app needs a new registration.
PRESET_OAUTH_REDIRECT_URI = f"{WEB_DOMAIN}/craft/v1/apps/oauth/callback"


def _build_presets() -> dict[ExternalAppType, Preset]:
    return {
        app_type: Preset(
            id=app_type.value,
            app_type=app_type,
            name=provider.spec.app_name,
            provider=provider,
        )
        for app_type, provider in PROVIDERS.items()
    }


PRESETS: dict[ExternalAppType, Preset] = _build_presets()


def get_preset(app_type: ExternalAppType) -> Preset | None:
    """The preset of ``app_type``, or None for CUSTOM."""
    return PRESETS.get(app_type)
