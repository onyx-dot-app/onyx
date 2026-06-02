"""Onyx-owned (operator-supplied) credentials for built-in external apps.

On managed cloud, Onyx owns the OAuth client credentials for built-in apps so
that tenant admins never have to register their own OAuth application. Operators
supply those credentials through the ``MANAGED_EXTERNAL_APP_CREDENTIALS`` env
var (a deployment secret); the tenant-provisioning path reads them here and
seeds them per tenant.

Format — a JSON object mapping a built-in ``app_type`` value to its credential
fields::

    {
      "gmail": {"client_id": "...", "client_secret": "..."},
      "slack": {"client_id": "...", "client_secret": "..."}
    }

Unset/empty is a valid no-op (self-hosted, or cloud before credentials are
provisioned): every built-in app is still provisioned, just without credentials
until they are configured.
"""

import json

from onyx.configs.app_configs import MANAGED_EXTERNAL_APP_CREDENTIALS
from onyx.db.enums import ExternalAppType
from onyx.utils.logger import setup_logger

logger = setup_logger()


def load_managed_external_app_credentials() -> dict[ExternalAppType, dict[str, str]]:
    """Parse the operator credential config into ``{app_type: {field: value}}``.

    Malformed entries are skipped with a logged warning rather than raising, so a
    single bad entry can't block tenant provisioning. Returns an empty dict when
    the env var is unset/empty/invalid.
    """
    raw = MANAGED_EXTERNAL_APP_CREDENTIALS.strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("MANAGED_EXTERNAL_APP_CREDENTIALS is not valid JSON; ignoring it.")
        return {}

    if not isinstance(parsed, dict):
        logger.error(
            "MANAGED_EXTERNAL_APP_CREDENTIALS must be a JSON object "
            "(app_type -> credentials); ignoring it."
        )
        return {}

    result: dict[ExternalAppType, dict[str, str]] = {}
    for key, value in parsed.items():
        # ExternalAppType values are upper-case (e.g. "GMAIL", "GOOGLE_CALENDAR");
        # accept any casing so operators can use natural keys like "gmail".
        try:
            app_type = ExternalAppType(str(key).strip().upper())
        except ValueError:
            logger.warning(
                "Unknown app_type '%s' in MANAGED_EXTERNAL_APP_CREDENTIALS; skipping.",
                key,
            )
            continue
        if app_type == ExternalAppType.CUSTOM:
            logger.warning(
                "CUSTOM apps cannot have Onyx-managed credentials; skipping the "
                "'custom' entry in MANAGED_EXTERNAL_APP_CREDENTIALS."
            )
            continue
        if not isinstance(value, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        ):
            logger.warning(
                "Credentials for '%s' must be a JSON object of string->string; "
                "skipping.",
                key,
            )
            continue
        result[app_type] = dict(value)

    return result
