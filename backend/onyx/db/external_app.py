import re
from typing import Any
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppUserCredential
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


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


def create_external_app__no_commit(
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
    """Create the backing Skill row and the ExternalApp that references
    it in one transaction. The skill row owns display metadata
    (name/description) and lifecycle (enabled); the external_app row
    owns gateway state (auth_template, upstream patterns, org creds).

    `create_skill` raises ``OnyxError(DUPLICATE_RESOURCE)`` on slug collision.
    """
    # Deferred import: `db.skill` imports `is_user_authenticated_for_app`
    # from this module to filter listings, so the dependency only flows
    # one way at module-load time.
    from onyx.db.skill import create_skill

    skill = create_skill(
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
    db_session.flush()
    return app


def update_external_app__no_commit(
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
    """Replace mutable fields on the external app and its linked skill.

    Skill-side fields: name, description, enabled.
    External-app-side fields: app_type, upstream_url_patterns,
    auth_template, organization_credentials.

    Slug, bundle, and sharing scope are out of scope here (each has its
    own update path in ``onyx.db.skill``).

    Raises ``OnyxError(NOT_FOUND)`` if no row with `external_app_id` exists.
    """
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

    db_session.flush()
    return app


def delete_external_app__no_commit(
    db_session: Session,
    external_app_id: int,
) -> str | None:
    """Delete the linked Skill (FK ON DELETE CASCADE removes the
    external_app row as well as user credentials). Returns the skill's
    ``bundle_file_id`` so the caller can clean up FileStore.

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
    db_session.flush()
    return bundle_file_id


def upsert_external_app_user_credential__no_commit(
    db_session: Session,
    external_app_id: int,
    user_id: UUID,
    user_credentials: dict[str, Any],
) -> ExternalAppUserCredential:
    """Create or replace the calling user's credentials for the given external app.

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
    - no enabled app's `upstream_urls` fully match the URL
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
        for pattern in app.upstream_urls:
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

    required_user_keys = set(app.auth_template.keys()) - set(
        app.organization_credentials.keys()
    )
    if not required_user_keys.issubset(stored_user_creds.keys()):
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
