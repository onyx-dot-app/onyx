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

# Matches `{placeholder}` references inside auth_template values. Used
# to figure out which credential parameter names the template depends
# on — those are the names whose values must be present somewhere
# (org_credentials or user_credentials) before the template can be
# substituted at injection time.
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
    """The credential parameter names a user must supply for this app.

    Computed from the `{placeholder}` references inside `auth_template`
    values, minus anything `organization_credentials` already pre-fills.
    Returned sorted so callers get deterministic ordering.

    Note: this looks at the *values* of `auth_template`, not the keys.
    The keys are HTTP header names (e.g. "Authorization"); the
    credential parameter names live inside the value templates (e.g.
    `{access_token}` in `"Bearer {access_token}"`).
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
    """Return mapping from external_app_id -> the user's credential row.

    Apps the user has never configured are simply absent from the mapping.
    """
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
    """Replace all mutable fields of an existing external app.

    Raises OnyxError(NOT_FOUND) if no row with `external_app_id` exists.
    """
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
    """Delete an external app and (via FK ON DELETE CASCADE) its user credentials.

    Raises OnyxError(NOT_FOUND) if no row with `external_app_id` exists.
    """
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
    """Create or replace the calling user's credentials for the given external app.

    Atomic via ON CONFLICT against the unique (external_app_id, user_id)
    constraint, so concurrent callers can't both insert a duplicate row.

    Raises OnyxError(NOT_FOUND) if no app with `external_app_id` exists.
    """
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
    """Resolve auth credentials for an outbound URL.

    Returns the matched app's `auth_template` with every `{placeholder}`
    substituted from the union of `organization_credentials` and the
    user's stored credentials. The egress proxy uses this to decide
    which auth headers/params to inject into an outbound request.

    Returns None when any of:
    - no enabled app's `upstream_url_patterns` fully match the URL
    - the user has no stored credentials for the matched app
    - the user's stored credentials don't cover every key the app expects
      them to provide
    - the auth template references a placeholder that no credential
      supplies (a misconfigured app — fail closed rather than inject a
      partially-templated header)

    `re.fullmatch` is used (not `re.search`/`re.match`) so a pattern like
    `https://api\\.example\\.com/.*` does not accidentally match
    `https://api.example.com.evil.com/foo`.

    Apps are scanned in id order for deterministic resolution if two
    apps happen to overlap on a URL.
    """
    # One round trip: every enabled app paired with the calling user's
    # credential row for it (NULL if not configured). Regex matching
    # stays in Python because Postgres regex (POSIX) and Python regex
    # (PCRE-ish) diverge on common features (`(?i)`, `\d`, lookbehinds),
    # and a mismatch between admin-side validation and proxy-side
    # matching is a footgun.
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
    """Substitute org + user credentials into the app's auth_template.

    Returns None if the user hasn't stored every required key, or if
    the template references a placeholder no credential supplies.
    """
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
    """Return the first enabled app whose `upstream_urls` regex
    fully-matches `url`. Same matching semantics as
    `get_external_app_credentials` but doesn't join the user
    credential row — used by `refresh_credentials`, which re-reads the
    credential row inside an advisory lock anyway.
    """
    stmt = (
        select(ExternalApp)
        .where(ExternalApp.enabled.is_(True))
        .order_by(ExternalApp.id)
    )
    for app in db_session.scalars(stmt).all():
        for pattern in app.upstream_urls:
            if re.fullmatch(pattern, url):
                return app
    return None


def _acquire_refresh_lock(db_session: Session, app_id: int, user_id: UUID) -> None:
    """Acquire a Postgres transaction-scoped advisory lock keyed on
    (app_id, hash(user_id)). Released automatically on commit/rollback.

    Serializes concurrent refresh attempts for the same (app, user)
    pair across processes — without this, two callers racing to
    refresh would each try to redeem the same refresh_token, and on
    providers that rotate refresh_tokens (Slack, Linear) one of them
    would lose and the user would be locked out.

    UUID → int4 by taking the first 4 bytes of the UUID — random
    enough that lock-key collisions across unrelated users are
    vanishingly rare, and a collision just means unrelated users
    serialize unnecessarily (no correctness impact).
    """
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
    """Refresh the user's OAuth tokens for the app matching `url`.

    Looks up the app by `url` (same matching as
    `get_external_app_credentials`), acquires a per-(app, user)
    advisory lock so concurrent callers don't race, calls the
    provider's refresh-token endpoint, merges the new tokens over the
    existing `user_credentials` (preserving fields the refresh
    response doesn't carry — team_id, authed_user_id, etc.), commits,
    and returns the new templated auth dict ready for header
    injection. Same return shape as `get_external_app_credentials`.

    Returns None if:
    - no enabled app's `upstream_urls` match the URL
    - the app isn't a built-in OAuth provider
    - the user has no stored credentials for the app
    - no refresh_token is stored (provider doesn't issue refresh
      tokens, or the original grant didn't include one)
    - the provider's `client_id`/`client_secret` are not configured
    - the provider rejected the refresh (revocation, expired refresh
      token, network/5xx error)

    A None return is the caller's signal that the user must
    re-authenticate.
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

    # Lock first, then re-read inside the lock so a sibling caller
    # who already refreshed gets their freshly-written tokens picked
    # up here instead of us trying to redeem an invalidated
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

    # Network call held inside the advisory lock so concurrent
    # refreshes serialize cleanly. Acceptable cost — refresh is rare
    # (once per token lifetime per user).
    refreshed = refresh_oauth_tokens(provider, client_id, client_secret, refresh_token)
    if refreshed is None:
        return None

    # Merge over existing creds. Providers like Google omit
    # refresh_token from refresh responses (they don't rotate); the
    # merge preserves the old refresh_token in that case. Providers
    # that rotate (Slack, Linear) include the new refresh_token in
    # `refreshed` and it correctly overwrites the old one.
    merged = {**user_cred.user_credentials, **refreshed}
    user_cred.user_credentials = merged
    db_session.flush()
    db_session.commit()

    return _resolve_credentials(matched_app, user_cred)
