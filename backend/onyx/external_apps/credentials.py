from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.external_app import get_external_app_by_id
from onyx.db.external_app import get_external_app_user_credential
from onyx.db.models import ExternalApp
from onyx.external_apps.providers.registry import get_endpoint_catalog
from onyx.external_apps.providers.registry import get_provider_for_app


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
    action_types: Sequence[str] | None = None,
) -> dict[str, str]:
    """Auth headers the egress proxy should inject for a *verified* request to
    ``external_app_id`` on behalf of ``user_id``.

    Returns ``{}`` when the app is gone or disabled (the linked skill's
    ``enabled`` flag is the proxy's kill switch), or when no header's
    placeholders can be filled. Merges the app's organization credentials with
    the user's stored credentials (the user's win on key conflicts), extends
    them with the provider's ``derive_credentials``, then renders the
    ``auth_template`` via :func:`build_auth_headers`. ``action_types`` is the
    request's matched catalog actions (strictest-first); the first with an
    ``EndpointSpec.auth_template`` overrides the app's stored template.
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

    provider = get_provider_for_app(app)
    if provider is not None:
        credentials = provider.derive_credentials(credentials)

    auth_template = app.auth_template
    if action_types:
        overrides = {
            endpoint.id.value: endpoint.auth_template
            for endpoint in get_endpoint_catalog(app.app_type)
            if endpoint.auth_template is not None
        }
        # First override in the list wins — assumes co-matched actions never
        # carry conflicting templates (true while overrides are host-disjoint).
        override = next((overrides[a] for a in action_types if a in overrides), None)
        if override is not None:
            auth_template = override

    return build_auth_headers(auth_template, credentials)


def app_is_available(db_session: Session, app: ExternalApp, user_id: UUID) -> bool:
    """Whether the gate should act on ``app`` for ``user_id`` — i.e. it's active
    and we have everything needed to serve the request.

    Distinguishes "no credential required" from "required credential unavailable":
    an enabled app with an empty ``auth_template`` (an allowlist-only app that
    injects nothing) is available; an app whose template can't be filled is not.
    A disabled skill (the proxy's kill switch) is never available. Injection
    re-resolves later with an OAuth refresh, so this verdict-time render is the
    cheap presence check, not the final one. Probes the stored template only —
    assumes per-action ``auth_template`` overrides are fillable iff it is.
    """
    if not app.skill.enabled:
        return False
    if not app.auth_template:
        return True
    return bool(resolve_injection_headers(db_session, app.id, user_id))
