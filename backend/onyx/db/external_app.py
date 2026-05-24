import re
from typing import Any
from uuid import UUID
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppUserCredential
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.built_in import EXTERNAL_APP_BUILT_IN_SKILL_IDS
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


def validate_auth_template(
    auth_template: dict[str, Any],
    organization_credentials: dict[str, Any],
) -> None:
    """Validate an external app's header credential template before persisting.

    The egress proxy injects ``auth_template`` headers (with ``{placeholder}``
    values filled from org + per-user credentials) into outbound requests. An
    app may legitimately inject *no* headers — e.g. an allowlist-only app that
    just grants the sandbox network access to its upstream patterns — so an
    empty template (and empty organization credentials) is allowed. When headers
    *are* provided, each must be a non-empty string name mapped to a non-empty
    string value; organization-credential keys must likewise be non-empty
    strings. Raises ``OnyxError(INVALID_INPUT)`` on any violation.

    Note: only ``{name}`` tokens matching the credential-key grammar are treated
    as placeholders (see ``_PLACEHOLDER_RE``); other braces are literal, so
    there is nothing further to validate about placeholder legality here.
    """
    for key, value in auth_template.items():
        if not isinstance(key, str) or not key.strip():
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "auth_template header names must be non-empty strings.",
            )
        if not isinstance(value, str) or not value.strip():
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"auth_template value for header '{key}' must be a non-empty string.",
            )
    for key in organization_credentials:
        if not isinstance(key, str) or not key.strip():
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "organization_credentials keys must be non-empty strings.",
            )


def is_user_authenticated_for_app(
    app: ExternalApp,
    user_cred: ExternalAppUserCredential | None,
) -> bool:
    """True iff the user has supplied every credential parameter the app's
    ``auth_template`` references that the org has not pre-filled. An
    app with no user-required keys (everything covered by
    ``organization_credentials``) is considered authenticated for every
    user, no credential row needed."""
    required = required_user_credential_keys(
        app.auth_template, app.organization_credentials
    )
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
    slug: str | None = None,
) -> ExternalApp:
    """Create the backing Skill row and the ExternalApp that references it,
    committing both atomically. The skill row owns display metadata
    (name/description) and lifecycle (enabled); the external_app row owns
    gateway state (auth_template, upstream patterns, org creds).

    The skill row's *shape* is derived from ``app_type``:

    - A built-in provider (``EXTERNAL_APP_BUILT_IN_SKILL_IDS``) gets a built-in
      skill row (``built_in_skill_id`` set, ``slug`` == that id) so it delivers
      its bundled on-disk content through the same path as a seeded built-in.
      Slug uniqueness means one instance per provider per tenant — a duplicate
      raises ``OnyxError(DUPLICATE_RESOURCE)``.
    - A ``CUSTOM`` app gets a custom (bundle-backed) skill row. ``slug`` is the
      uploaded bundle's filename-derived slug (see the custom-app create
      endpoint); when omitted, a fresh ``custom-<uuid>`` slug is generated so
      bundle-less callers still get a unique, collision-free row.
    """
    from onyx.db.skill import create_built_in_skill_row__no_commit
    from onyx.db.skill import create_skill__no_commit

    built_in_skill_id = EXTERNAL_APP_BUILT_IN_SKILL_IDS.get(app_type)
    if built_in_skill_id is not None:
        skill = create_built_in_skill_row__no_commit(
            built_in_skill_id=built_in_skill_id,
            name=name,
            description=description,
            is_public=is_public,
            enabled=enabled,
            author_user_id=author_user_id,
            db_session=db_session,
        )
    else:
        # CUSTOM: use the bundle's filename-derived slug, falling back to a
        # generated one when no bundle is supplied (e.g. the JSON upsert path).
        custom_slug = slug or f"{app_type.value.lower()}-{uuid4().hex[:8]}"
        skill = create_skill__no_commit(
            slug=custom_slug,
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
    new_bundle_file_id: str | None = None,
    new_bundle_sha256: str | None = None,
) -> tuple[ExternalApp, str | None]:
    """Replace mutable fields on the external app and its linked skill,
    committing both atomically. Returns ``(app, old_bundle_file_id)``.

    Skill-side fields: name, description, enabled.
    External-app-side fields: upstream_url_patterns, auth_template,
    organization_credentials.

    ``app_type`` is immutable — it's the discriminator the OAuth dispatch layer
    keys off and what the backing skill's definition source is bound to, so it's
    passed for validation only. Passing a value that differs from the stored one
    raises; this also blocks editing a built-in app through the custom-app path
    (which passes ``CUSTOM``) and vice versa.

    Bundle replacement (custom apps only): when ``new_bundle_file_id`` /
    ``new_bundle_sha256`` are given the skill's bundle is swapped (slug
    unchanged) and the *previous* ``bundle_file_id`` is returned so the caller
    can delete that blob after the commit — never inline. When omitted the
    existing bundle is kept and the returned old id is ``None``. Built-in
    callers leave these unset and ignore the returned id.

    Raises ``OnyxError(NOT_FOUND)`` if no row with `external_app_id` exists,
    or ``OnyxError(INVALID_INPUT)`` if `app_type` differs from the stored value.
    """
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )

    # app_type is immutable. Changing it would silently rebind the skill's
    # definition source.
    if app.app_type != app_type:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"app_type is immutable; cannot change from "
            f"'{app.app_type.value}' to '{app_type.value}'.",
        )

    app.skill.name = name
    app.skill.description = description
    app.skill.enabled = enabled

    old_bundle_file_id: str | None = None
    if new_bundle_file_id is not None:
        # Keep the slug; only the bundle bytes change.
        old_bundle_file_id = app.skill.bundle_file_id
        app.skill.bundle_file_id = new_bundle_file_id
        app.skill.bundle_sha256 = new_bundle_sha256

    app.upstream_url_patterns = upstream_url_patterns
    app.auth_template = auth_template
    app.organization_credentials = organization_credentials

    db_session.commit()
    return app, old_bundle_file_id


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
