import re
from typing import Any
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppUserCredential
from onyx.db.models import Skill
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


def is_user_authenticated_for_app(
    app: ExternalApp,
    user_cred: ExternalAppUserCredential | None,
) -> bool:
    """True iff the user has supplied every credential key the app's
    ``auth_template`` references that the org has not pre-filled. An
    app with no user-required keys (everything covered by
    ``organization_credentials``) is considered authenticated for every
    user, no credential row needed."""
    required = [k for k in app.auth_template if k not in app.organization_credentials]
    if not required:
        return True
    if user_cred is None:
        return False
    return all(k in user_cred.user_credentials for k in required)


def get_external_app_by_id(
    db_session: Session,
    external_app_id: int,
) -> ExternalApp | None:
    stmt = (
        select(ExternalApp)
        .options(selectinload(ExternalApp.skill))
        .where(ExternalApp.id == external_app_id)
    )
    return db_session.scalar(stmt)


def get_external_apps(
    db_session: Session,
) -> list[ExternalApp]:
    stmt = (
        select(ExternalApp)
        .options(selectinload(ExternalApp.skill))
        .order_by(ExternalApp.id)
    )
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


def create_external_app(
    db_session: Session,
    slug: str,
    name: str,
    description: str,
    bundle_file_id: str,
    bundle_sha256: str,
    app_type: ExternalAppType,
    upstream_url_patterns: list[str],
    auth_template: dict[str, Any],
    organization_credentials: dict[str, Any],
    enabled: bool = True,
    is_public: bool = False,
    author_user_id: UUID | None = None,
) -> ExternalApp:
    """Create the backing Skill row and the ExternalApp that references it,
    committing both atomically. The skill row owns display metadata
    (name/description) and lifecycle (enabled); the external_app row owns
    gateway state (auth_template, upstream patterns, org creds).

    `create_skill` raises ``OnyxError(DUPLICATE_RESOURCE)`` on slug collision
    (before anything is committed).
    """
    # Deferred import: `db.skill` imports `is_user_authenticated_for_app`
    # from this module to filter listings, so the dependency only flows
    # one way at module-load time.
    from onyx.db.skill import create_skill__no_commit

    skill = create_skill__no_commit(
        slug=slug,
        name=name,
        description=description,
        bundle_file_id=bundle_file_id,
        bundle_sha256=bundle_sha256,
        is_public=is_public,
        author_user_id=author_user_id,
        db_session=db_session,
    )
    # `create_skill` hardcodes enabled=True; honour the caller's intent.
    if not enabled:
        skill.enabled = False
    app = ExternalApp(
        skill_id=skill.id,
        app_type=app_type,
        upstream_url_patterns=upstream_url_patterns,
        auth_template=auth_template,
        organization_credentials=organization_credentials,
    )
    db_session.add(app)
    db_session.commit()
    return app


def update_external_app(
    db_session: Session,
    external_app_id: int,
    name: str,
    description: str,
    enabled: bool,
    app_type: ExternalAppType,
    upstream_url_patterns: list[str],
    auth_template: dict[str, Any],
    organization_credentials: dict[str, Any],
) -> ExternalApp:
    """Replace mutable fields on the external app and its linked skill,
    committing both atomically.

    Skill-side fields: name, description, enabled.
    External-app-side fields: app_type, upstream_url_patterns,
    auth_template, organization_credentials.

    Slug, bundle, and sharing scope are out of scope here (each has its
    own update path in ``onyx.db.skill``).

    Raises ``OnyxError(NOT_FOUND)`` if no row with `external_app_id` exists.
    """
    _validate_upstream_url_patterns(upstream_url_patterns)
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )

    app.skill.name = name
    app.skill.description = description
    app.skill.enabled = enabled

    app.app_type = app_type
    app.upstream_url_patterns = upstream_url_patterns
    app.auth_template = auth_template
    app.organization_credentials = organization_credentials

    db_session.commit()
    return app


def delete_external_app(
    db_session: Session,
    external_app_id: int,
) -> str | None:
    """Delete the linked Skill (FK ON DELETE CASCADE removes the
    external_app row as well as user credentials) and commit. Returns the
    skill's ``bundle_file_id`` so the caller can clean up FileStore *after*
    the delete is committed.

    Raises ``OnyxError(NOT_FOUND)`` if no row with `external_app_id` exists.
    """
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )

    bundle_file_id = app.skill.bundle_file_id
    db_session.delete(app.skill)
    db_session.commit()
    return bundle_file_id


def upsert_external_app_user_credential(
    db_session: Session,
    external_app_id: int,
    user_id: UUID,
    user_credentials: dict[str, Any],
) -> ExternalAppUserCredential:
    """Create or replace the calling user's credentials for the given external
    app, and commit.

    Atomic via ON CONFLICT against the unique (external_app_id, user_id)
    constraint, so concurrent callers can't both insert a duplicate row.

    Raises ``OnyxError(NOT_FOUND)`` if no app with `external_app_id` exists.
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
    db_session.commit()
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
    - the auth template fails to resolve — missing placeholder
      (user-missing or app-misconfigured), malformed brace, bad format
      spec, etc. Fail closed rather than inject a partially-templated
      header.

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
        .join(Skill, Skill.id == ExternalApp.skill_id)
        .outerjoin(
            ExternalAppUserCredential,
            and_(
                ExternalAppUserCredential.external_app_id == ExternalApp.id,
                ExternalAppUserCredential.user_id == user_id,
            ),
        )
        .where(Skill.enabled.is_(True))
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

    Returns None on any template-resolution failure — missing
    placeholder, malformed brace, bad format spec, positional reference
    against a mapping, etc. Fail closed rather than inject a
    partially-templated header. Output keys in `auth_template` are
    independent of placeholder names: a template
    `{"Authorization": "Bearer {access_token}"}` requires the credential
    key `access_token`, not `Authorization`.
    """
    stored_user_creds: dict[str, Any] = (
        user_cred.user_credentials if user_cred is not None else {}
    )

    combined_creds: dict[str, Any] = {
        **app.organization_credentials,
        **stored_user_creds,
    }

    resolved: dict[str, Any] = {}
    for key, value in app.auth_template.items():
        if isinstance(value, str):
            try:
                resolved[key] = value.format_map(combined_creds)
            except (LookupError, ValueError, AttributeError, TypeError):
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
