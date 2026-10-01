"""EE perm-sync helpers that still use the Confluence client directly.

Temporary: #15454 moves these calls to ``ConfluenceSourceOperations`` operations
and deletes this module, including the re-exports below.
"""

from requests import HTTPError

from onyx.connectors.confluence.source_operations import (
    ConfluenceRestSpacePermissionsNotAvailableError,
)
from onyx.connectors.confluence.source_operations import (
    _OnyxConfluence as OnyxConfluence,
)
from onyx.utils.logger import setup_logger

__all__ = [
    "ConfluenceRestSpacePermissionsNotAvailableError",
    "OnyxConfluence",
    "get_user_email_from_userkey__server",
    "get_user_email_from_username__server",
]

logger = setup_logger()

# Both caches are keyed by (confluence instance base url, identifier). The
# Confluence Server/DC username and userKey namespaces are per-instance, so a bare
# identifier key would let one instance's user resolve to another instance's email
# when several Confluence connectors run in the same multi-tenant worker process.
_USER_EMAIL_CACHE: dict[tuple[str, str], str | None] = {}
# Separate cache from _USER_EMAIL_CACHE: the DC 9.1+ REST space-permissions
# response only includes a user's userKey (CONFSERVER-100505), not their
# username, so we have to resolve email by a different identifier.
_USER_KEY_TO_EMAIL_CACHE: dict[tuple[str, str], str | None] = {}


def get_user_email_from_username__server(
    confluence_client: OnyxConfluence, user_name: str
) -> str | None:
    global _USER_EMAIL_CACHE
    cache_key = (confluence_client._url, user_name)
    if _USER_EMAIL_CACHE.get(cache_key) is None:
        try:
            response = confluence_client.get_mobile_parameters(user_name)
            email = response.get("email")
        except HTTPError as e:
            status_code = e.response.status_code if e.response is not None else "N/A"
            logger.warning(
                "Failed to get confluence email for %s: HTTP %s - %s",
                user_name,
                status_code,
                e,
            )
            # For now, we'll just return None and log a warning. This means
            # we will keep retrying to get the email every group sync.
            email = None
        except Exception as e:
            logger.warning(
                "Failed to get confluence email for %s: %s - %s",
                user_name,
                type(e).__name__,
                e,
            )
            email = None
        _USER_EMAIL_CACHE[cache_key] = email
    return _USER_EMAIL_CACHE[cache_key]


def get_user_email_from_userkey__server(
    confluence_client: OnyxConfluence, user_key: str
) -> str | None:
    """userKey -> email resolver for Confluence Data Center.

    Parallels get_user_email_from_username__server but keyed on userKey
    instead of username, because the DC 9.1+ space-permissions REST API
    only exposes userKey on user subjects (CONFSERVER-100505 -- still
    unresolved as of the 10.x line).

    Cached separately from _USER_EMAIL_CACHE because the keyspaces are
    different (userKey is opaque hex, username is human-readable).
    """
    global _USER_KEY_TO_EMAIL_CACHE
    cache_key = (confluence_client._url, user_key)
    if cache_key not in _USER_KEY_TO_EMAIL_CACHE:
        try:
            response = confluence_client.get_user_details_by_userkey(user_key)
            email = response.get("email") if isinstance(response, dict) else None
        except HTTPError as e:
            status_code = e.response.status_code if e.response is not None else "N/A"
            logger.warning(
                "Failed to get confluence email for userKey %s: HTTP %s - %s",
                user_key,
                status_code,
                e,
            )
            email = None
        except Exception as e:
            logger.warning(
                "Failed to get confluence email for userKey %s: %s - %s",
                user_key,
                type(e).__name__,
                e,
            )
            email = None
        _USER_KEY_TO_EMAIL_CACHE[cache_key] = email
    return _USER_KEY_TO_EMAIL_CACHE[cache_key]
