import re
from typing import Any
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppUserCredential
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


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
