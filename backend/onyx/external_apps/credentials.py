from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.oauth_token_manager import get_tool_access_token
from onyx.db.external_app import (
    get_external_app_by_id,
    get_external_app_user_credential,
    is_user_authenticated_for_app,
)
from onyx.db.models import ExternalApp
from onyx.db.users import fetch_user_by_id


class ExternalAppCredentialsError(Exception):
    """An app requires a user credential that is missing or cannot be refreshed."""


def build_auth_headers(
    auth_template: dict[str, Any],
    credentials: dict[str, Any],
) -> dict[str, str]:
    """Fill each ``auth_template`` header value's ``{placeholder}`` fields from
    ``credentials``, returning ``{header_name: rendered_value}``.

    A header whose template references a credential not present in
    ``credentials`` is **omitted** — the request goes out without that header
    rather than with a half-filled secret. ``str.format`` substitutes values
    once (it does not re-interpret braces inside the substituted values), so a
    credential value containing ``{`` is safe.
    """
    headers: dict[str, str] = {}
    for name, template in auth_template.items():
        if not isinstance(template, str):
            continue
        try:
            headers[name] = template.format(**credentials)
        except (KeyError, IndexError, ValueError, AttributeError, TypeError):
            # Render failed for this header
            continue
    return headers


def resolve_injection_headers(
    db_session: Session,
    external_app_id: int,
    user_id: UUID,
) -> dict[str, str]:
    """Auth headers the egress proxy should inject for a *verified* request to
    ``external_app_id`` on behalf of ``user_id``.

    Returns ``{}`` when the app is gone or disabled, or when no header's
    placeholders can be filled. Merges the app's organization credentials with
    the user's stored credentials (the user's win on key conflicts), then
    renders the ``auth_template`` via :func:`build_auth_headers`. OpenAPI apps
    use their source action's per-user OAuth or login token when configured.
    Missing required user authentication raises ``ExternalAppCredentialsError``.
    """
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None or not app.enabled:
        return {}

    credentials: dict[str, Any] = dict(
        app.organization_credentials.get_value(apply_mask=False)
    )
    if app.openapi_tool_id is None:
        user_cred = get_external_app_user_credential(
            db_session, external_app_id=external_app_id, user_id=user_id
        )
        if user_cred is not None:
            credentials.update(user_cred.user_credentials.get_value(apply_mask=False))

    headers = build_auth_headers(app.auth_template, credentials)
    tool = app.openapi_tool
    if tool is not None and (tool.oauth_config_id is not None or tool.passthrough_auth):
        access_token = get_tool_access_token(
            oauth_config_id=tool.oauth_config_id,
            passthrough_auth=tool.passthrough_auth,
            user=fetch_user_by_id(db_session, user_id),
            db_session=db_session,
        )
        if not access_token:
            raise ExternalAppCredentialsError(
                "Connect or reconnect this app before using its OpenAPI action in Craft."
                if tool.oauth_config_id is not None
                else "Sign in to Onyx with your organization's OAuth provider before using this action in Craft."
            )
        headers = {
            key: value
            for key, value in headers.items()
            if key.lower() != "authorization"
        }
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def app_is_available(db_session: Session, app: ExternalApp, user_id: UUID) -> bool:
    """Whether the gate should act on ``app`` for ``user_id`` — i.e. it's active
    and we have everything needed to serve the request.

    Distinguishes "no credential required" from "required credential unavailable":
    an app with an empty ``auth_template`` (an allowlist-only app that
    injects nothing) is available; an app whose template can't be filled is not.
    Injection re-resolves later with an OAuth refresh, so this verdict-time render is the
    cheap presence check, not the final one.
    """
    if not app.enabled:
        return False
    if app.openapi_tool_id is not None:
        return is_user_authenticated_for_app(
            app, None, db_session=db_session, user_id=user_id
        )
    if not app.auth_template:
        return True
    return bool(resolve_injection_headers(db_session, app.id, user_id))
