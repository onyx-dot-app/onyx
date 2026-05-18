import re
from typing import Any
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppUserCredential
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers import get_provider_for_app
from onyx.external_apps.refresh import refresh_oauth_tokens
from onyx.utils.logger import setup_logger

logger = setup_logger()

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _placeholders_in_template(auth_template: dict[str, Any]) -> set[str]:
    placeholders: set[str] = set()
    for value in auth_template.values():
        if isinstance(value, str):
            placeholders.update(_PLACEHOLDER_RE.findall(value))
    return placeholders


def required_user_credential_keys(
    auth_template: dict[str, Any],
    organization_credentials: dict[str, Any],
) -> list[str]:
    """Credential parameter names the user must supply, derived from
    `{placeholder}` references in `auth_template` values minus what
    `organization_credentials` pre-fills. Returned sorted.

    Looks at template *values*, not keys — keys are header names,
    placeholders inside the values are the credential parameter names.
    """
    return sorted(
        _placeholders_in_template(auth_template) - organization_credentials.keys()
    )


def get_external_app_by_id(
    db_session: Session,
    external_app_id: int,
) -> ExternalApp | None:
    stmt = select(ExternalApp).where(ExternalApp.id == external_app_id)
    return db_session.scalar(stmt)


def get_external_apps(
    db_session: Session,
) -> list[ExternalApp]:
    stmt = select(ExternalApp).order_by(ExternalApp.id)
    return list(db_session.scalars(stmt).all())


def get_user_credentials_by_app_id(
    db_session: Session,
    user_id: UUID,
) -> dict[int, ExternalAppUserCredential]:
    """Map of external_app_id → credential row for the user. Apps the
    user hasn't configured are absent from the mapping."""
    stmt = select(ExternalAppUserCredential).where(
        ExternalAppUserCredential.user_id == user_id
    )
    return {row.external_app_id: row for row in db_session.scalars(stmt).all()}


def create_external_app__no_commit(
    db_session: Session,
    name: str,
    description: str,
    app_type: ExternalAppType,
    upstream_url_patterns: list[str],
    auth_template: dict[str, Any],
    organization_credentials: dict[str, Any],
    enabled: bool,
) -> ExternalApp:
    app = ExternalApp(
        name=name,
        description=description,
        app_type=app_type,
        upstream_url_patterns=upstream_url_patterns,
        auth_template=auth_template,
        organization_credentials=organization_credentials,
        enabled=enabled,
    )
    db_session.add(app)
    db_session.flush()
    return app


def update_external_app__no_commit(
    db_session: Session,
    external_app_id: int,
    name: str,
    description: str,
    app_type: ExternalAppType,
    upstream_url_patterns: list[str],
    auth_template: dict[str, Any],
    organization_credentials: dict[str, Any],
    enabled: bool,
) -> ExternalApp:
    """Replace all mutable fields. Raises NOT_FOUND if no row."""
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )

    app.name = name
    app.description = description
    app.app_type = app_type
    app.upstream_url_patterns = upstream_url_patterns
    app.auth_template = auth_template
    app.organization_credentials = organization_credentials
    app.enabled = enabled

    db_session.flush()
    return app


def delete_external_app__no_commit(
    db_session: Session,
    external_app_id: int,
) -> None:
    """User credentials cascade via FK ON DELETE CASCADE."""
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )

    db_session.delete(app)
    db_session.flush()


def upsert_external_app_user_credential__no_commit(
    db_session: Session,
    external_app_id: int,
    user_id: UUID,
    user_credentials: dict[str, Any],
) -> ExternalAppUserCredential:
    """Atomic via ON CONFLICT on (external_app_id, user_id) — concurrent
    callers can't insert duplicate rows."""
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )

    stmt = pg_insert(ExternalAppUserCredential).values(
        external_app_id=external_app_id,
        user_id=user_id,
        user_credentials=user_credentials,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            ExternalAppUserCredential.external_app_id,
            ExternalAppUserCredential.user_id,
        ],
        set_={"user_credentials": stmt.excluded.user_credentials},
    ).returning(ExternalAppUserCredential)

    cred = db_session.scalars(stmt).one()
    db_session.flush()
    return cred


def get_external_app_credentials(
    db_session: Session,
    user_id: UUID,
    url: str,
) -> dict[str, Any] | None:
    """Resolve the auth headers/params to inject on an outbound URL.

    Uses `re.fullmatch` (not `search`/`match`) so a pattern like
    `https://api\\.example\\.com/.*` cannot match
    `https://api.example.com.evil.com/foo`.

    Returns None if no enabled app matches, the user has no creds,
    a required placeholder is unfilled, or the template references
    something nothing provides.
    """
    # One round trip: every enabled app + the caller's credential row
    # if any. Regex matching stays in Python because Postgres regex
    # (POSIX) and Python regex (PCRE-ish) diverge on common features.
    stmt = (
        select(ExternalApp, ExternalAppUserCredential)
        .outerjoin(
            ExternalAppUserCredential,
            and_(
                ExternalAppUserCredential.external_app_id == ExternalApp.id,
                ExternalAppUserCredential.user_id == user_id,
            ),
        )
        .where(ExternalApp.enabled.is_(True))
        .order_by(ExternalApp.id)
    )

    for app, user_cred in db_session.execute(stmt).all():
        for pattern in app.upstream_url_patterns:
            if re.fullmatch(pattern, url):
                return _resolve_credentials(app, user_cred)
    return None


def _resolve_credentials(
    app: ExternalApp,
    user_cred: ExternalAppUserCredential | None,
) -> dict[str, Any] | None:
    stored_user_creds: dict[str, Any] = (
        user_cred.user_credentials if user_cred is not None else {}
    )

    required_user_keys = required_user_credential_keys(
        app.auth_template, app.organization_credentials
    )
    if not set(required_user_keys).issubset(stored_user_creds.keys()):
        return None

    combined_creds: dict[str, Any] = {
        **app.organization_credentials,
        **stored_user_creds,
    }

    resolved: dict[str, Any] = {}
    for key, value in app.auth_template.items():
        if isinstance(value, str):
            try:
                resolved[key] = value.format_map(combined_creds)
            except KeyError:
                return None
        else:
            resolved[key] = value
    return resolved


def _find_enabled_app_for_url(db_session: Session, url: str) -> ExternalApp | None:
    stmt = (
        select(ExternalApp)
        .where(ExternalApp.enabled.is_(True))
        .order_by(ExternalApp.id)
    )
    for app in db_session.scalars(stmt).all():
        for pattern in app.upstream_url_patterns:
            if re.fullmatch(pattern, url):
                return app
    return None


def _acquire_refresh_lock(db_session: Session, app_id: int, user_id: UUID) -> None:
    """Postgres advisory lock on (app_id, user_id) — serializes
    concurrent refreshes for the same user+app so one caller doesn't
    invalidate another's refresh_token on rotating providers."""
    # UUID → int4 by taking 4 bytes. Collisions across unrelated users
    # only cause harmless serialization, never correctness issues.
    user_key = int.from_bytes(user_id.bytes[:4], "big") % (2**31 - 1)
    db_session.execute(
        text("SELECT pg_advisory_xact_lock(:k1, :k2)"),
        {"k1": app_id, "k2": user_key},
    )


def refresh_credentials(
    db_session: Session,
    user_id: UUID,
    url: str,
) -> dict[str, Any] | None:
    """Refresh OAuth tokens for the app matching `url`.

    Returns the new templated auth dict (same shape as
    `get_external_app_credentials`), or None if refresh isn't
    possible — caller treats None as "user must re-authenticate."
    """
    matched_app = _find_enabled_app_for_url(db_session, url)
    if matched_app is None:
        return None

    provider = get_provider_for_app(matched_app)
    if provider is None:
        logger.warning(
            "refresh_credentials called for app '%s' which is not a "
            "built-in OAuth provider",
            matched_app.name,
        )
        return None

    # Lock first, re-read inside — picks up a sibling caller's
    # freshly-written tokens instead of redeeming a now-invalidated
    # refresh_token.
    _acquire_refresh_lock(db_session, matched_app.id, user_id)

    user_cred = db_session.scalar(
        select(ExternalAppUserCredential).where(
            ExternalAppUserCredential.external_app_id == matched_app.id,
            ExternalAppUserCredential.user_id == user_id,
        )
    )
    if user_cred is None:
        return None

    refresh_token = user_cred.user_credentials.get("refresh_token")
    if not refresh_token:
        return None

    client_id = matched_app.organization_credentials.get("client_id")
    client_secret = matched_app.organization_credentials.get("client_secret")
    if not client_id or not client_secret:
        logger.warning(
            "Cannot refresh %s tokens: org_credentials missing "
            "client_id/client_secret",
            matched_app.name,
        )
        return None

    # Network call inside the lock — refresh is rare per token
    # lifetime, so the held lock cost is negligible.
    refreshed = refresh_oauth_tokens(provider, client_id, client_secret, refresh_token)
    if refreshed is None:
        return None

    # Merge: Google's refresh response omits refresh_token (no
    # rotation), so the old value survives; Slack/Linear rotate and
    # the new value overwrites.
    merged = {**user_cred.user_credentials, **refreshed}
    user_cred.user_credentials = merged
    db_session.flush()
    db_session.commit()

    return _resolve_credentials(matched_app, user_cred)
