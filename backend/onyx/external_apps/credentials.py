from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.external_app import get_external_app_by_id
from onyx.db.external_app import get_external_app_user_credential
from onyx.db.models import ExternalApp


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

    Returns ``{}`` when the app is gone or disabled (the linked skill's
    ``enabled`` flag is the proxy's kill switch), or when no header's
    placeholders can be filled. Merges the app's organization credentials with
    the user's stored credentials (the user's win on key conflicts), then
    renders the ``auth_template`` via :func:`build_auth_headers`.
    """
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None or not app.skill.enabled:
        return {}

    credentials: dict[str, Any] = dict(
        app.organization_credentials.get_value(apply_mask=False)
    )
    user_cred = get_external_app_user_credential(
        db_session, external_app_id=external_app_id, user_id=user_id
    )
    if user_cred is not None:
        credentials.update(user_cred.user_credentials.get_value(apply_mask=False))

    return build_auth_headers(app.auth_template, credentials)


def app_is_available(db_session: Session, app: ExternalApp, user_id: UUID) -> bool:
    """Whether the gate should act on ``app`` for ``user_id`` — i.e. it's active
    and we have everything needed to serve the request.

    Distinguishes "no credential required" from "required credential unavailable":
    an enabled app with an empty ``auth_template`` (an allowlist-only app that
    injects nothing) is available; an app whose template can't be filled is not.
    A disabled skill (the proxy's kill switch) is never available. Injection
    re-resolves later with an OAuth refresh, so this verdict-time render is the
    cheap presence check, not the final one.
    """
    if not app.skill.enabled:
        return False
    if not app.auth_template:
        return True
    return bool(resolve_injection_headers(db_session, app.id, user_id))
