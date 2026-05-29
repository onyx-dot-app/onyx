import re
from typing import Any
from uuid import UUID
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppPolicy
from onyx.db.models import ExternalAppUserCredential
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.built_in import EXTERNAL_APP_BUILT_IN_SKILL_IDS
from onyx.utils.encryption import is_masked_credential
from onyx.utils.logger import setup_logger
from onyx.utils.sensitive import SensitiveValue

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
    """Sorted credential parameter names the user must supply: `{placeholder}`
    references in `auth_template` values not pre-filled by
    `organization_credentials`."""
    return sorted(
        _placeholders_in_template(auth_template) - organization_credentials.keys()
    )


def validate_auth_template(
    auth_template: dict[str, Any],
    organization_credentials: dict[str, Any],
) -> None:
    """Validate an app's header credential template before persisting.

    An empty template is allowed (e.g. an allowlist-only app that injects no
    headers). When headers are present, each name and value must be a non-empty
    string, as must every organization-credential key. Raises
    ``OnyxError(INVALID_INPUT)`` on violation.
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


def resolve_masked_credentials(
    incoming: dict[str, str],
    existing: SensitiveValue[dict[str, Any]] | None,
) -> dict[str, str]:
    """Restore real secret values when the caller submits masked placeholders."""
    existing_values = (
        existing.get_value(apply_mask=False) if existing is not None else {}
    )
    resolved: dict[str, str] = {}
    for key, value in incoming.items():
        if is_masked_credential(value):
            if key not in existing_values:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"Credential '{key}' was submitted masked but has no stored "
                    "value to restore — provide the actual value.",
                )
            resolved[key] = existing_values[key]
        else:
            resolved[key] = value
    return resolved


def is_user_authenticated_for_app(
    app: ExternalApp,
    user_cred: ExternalAppUserCredential | None,
) -> bool:
    """True iff the user has supplied every credential parameter the app's
    ``auth_template`` requires that the org hasn't pre-filled. Apps with no
    user-required keys need no credential row."""
    required = required_user_credential_keys(
        app.auth_template, app.organization_credentials.get_value(apply_mask=False)
    )
    if not required:
        return True
    if user_cred is None:
        return False
    stored = user_cred.user_credentials.get_value(apply_mask=False)
    return all(k in stored for k in required)


def get_external_app_by_id(
    db_session: Session,
    external_app_id: int,
) -> ExternalApp | None:
    stmt = (
        select(ExternalApp)
        .options(
            selectinload(ExternalApp.skill),
            selectinload(ExternalApp.policies),
        )
        .where(ExternalApp.id == external_app_id)
    )
    return db_session.scalar(stmt)


def get_external_apps(
    db_session: Session,
) -> list[ExternalApp]:
    stmt = (
        select(ExternalApp)
        .options(
            selectinload(ExternalApp.skill),
            selectinload(ExternalApp.policies),
        )
        .order_by(ExternalApp.id)
    )
    return list(db_session.scalars(stmt).all())


def get_user_credentials_by_app_id(
    db_session: Session,
    user_id: UUID,
) -> dict[int, ExternalAppUserCredential]:
    """Map external_app_id -> the user's credential row. Apps the user never
    configured are absent."""
    stmt = select(ExternalAppUserCredential).where(
        ExternalAppUserCredential.user_id == user_id
    )
    return {row.external_app_id: row for row in db_session.scalars(stmt).all()}


def get_external_app_user_credential(
    db_session: Session,
    *,
    external_app_id: int,
    user_id: UUID,
) -> ExternalAppUserCredential | None:
    """The calling user's stored credentials for one app, or None if unset."""
    return db_session.scalar(
        select(ExternalAppUserCredential).where(
            ExternalAppUserCredential.external_app_id == external_app_id,
            ExternalAppUserCredential.user_id == user_id,
        )
    )


def create_external_app(
    db_session: Session,
    name: str,
    description: str,
    bundle_file_id: str,
    bundle_sha256: str,
    app_type: ExternalAppType,
    upstream_url_patterns: list[str],
    auth_template: dict[str, Any],
    organization_credentials: dict[str, str],
    enabled: bool = True,
    is_public: bool = False,
    author_user_id: UUID | None = None,
    slug: str | None = None,
    action_policies: dict[str, EndpointPolicy] | None = None,
) -> ExternalApp:
    """Create the backing Skill row and the ExternalApp that references it,
    committing atomically. The skill owns display metadata + lifecycle; the
    external_app owns gateway state.

    Built-in providers (``EXTERNAL_APP_BUILT_IN_SKILL_IDS``) get a built-in
    skill row whose slug is the provider id, so slug uniqueness means one
    instance per provider per tenant (duplicate raises ``DUPLICATE_RESOURCE``).
    CUSTOM apps get a bundle-backed skill using ``slug``, or a generated
    ``custom-<uuid>`` slug when omitted.
    """
    from onyx.db.skill import create_built_in_skill_row__no_commit
    from onyx.db.skill import create_skill__no_commit

    # No existing app to restore from on create, so a masked value is rejected.
    organization_credentials = resolve_masked_credentials(
        organization_credentials, None
    )

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
    if action_policies is not None:
        db_session.flush()  # assign app.id before writing its policy rows
        _write_policies__no_commit(db_session, app.id, action_policies)
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
    organization_credentials: dict[str, str],
    new_bundle_file_id: str | None = None,
    new_bundle_sha256: str | None = None,
    action_policies: dict[str, EndpointPolicy] | None = None,
) -> tuple[ExternalApp, str | None]:
    """Replace mutable fields on the external app and its linked skill,
    committing atomically. Returns ``(app, old_bundle_file_id)``.

    ``app_type`` is immutable (it's the dispatch discriminator); passing a value
    differing from the stored one raises, which also blocks cross-editing
    built-in vs custom apps.

    For custom apps, passing ``new_bundle_file_id``/``new_bundle_sha256`` swaps
    the bundle (slug unchanged) and returns the previous ``bundle_file_id`` so
    the caller can delete that blob after commit; otherwise the old id is
    ``None``.

    Raises ``OnyxError(NOT_FOUND)`` if the app doesn't exist, or
    ``INVALID_INPUT`` if ``app_type`` differs from the stored value.
    """
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )

    # app_type is immutable. Changing it would silently rebind the skill's
    # definition source
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
    # Admin responses mask org credentials; restore any masked value the form
    # echoed back so an unchanged secret isn't overwritten with its mask.
    app.organization_credentials = resolve_masked_credentials(  # ty: ignore[invalid-assignment]
        organization_credentials, app.organization_credentials
    )

    if action_policies is not None:
        _write_policies__no_commit(db_session, app.id, action_policies)

    db_session.commit()
    return app, old_bundle_file_id


def get_policies(
    db_session: Session,
    external_app_id: int,
) -> dict[str, EndpointPolicy]:
    """Return the app's stored per-action policy overrides as
    ``{action_id: policy}``. Sparse — only actions the admin has set."""
    rows = db_session.scalars(
        select(ExternalAppPolicy).where(
            ExternalAppPolicy.external_app_id == external_app_id
        )
    ).all()
    return {row.action_id: row.policy for row in rows}


def _write_policies__no_commit(
    db_session: Session,
    external_app_id: int,
    policies: dict[str, EndpointPolicy],
) -> None:
    """Replace the app's per-action policy rows with exactly ``policies`` (full
    delete + insert). No commit — runs inside the create/update transaction so
    the app and its policies persist atomically. ``action_id`` validation
    against the provider catalog is the caller's responsibility.
    """
    db_session.execute(
        delete(ExternalAppPolicy).where(
            ExternalAppPolicy.external_app_id == external_app_id
        )
    )
    for action_id, policy in policies.items():
        db_session.add(
            ExternalAppPolicy(
                external_app_id=external_app_id,
                action_id=action_id,
                policy=policy,
            )
        )


def delete_external_app(
    db_session: Session,
    external_app_id: int,
) -> str | None:
    """Delete the linked Skill (cascade removes the external_app row and user
    credentials) and commit. Returns the skill's ``bundle_file_id`` so the
    caller can clean up FileStore after the commit. Raises
    ``OnyxError(NOT_FOUND)`` if the app doesn't exist.
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
    """Create or replace the calling user's credentials for the app, and commit.
    Atomic via ON CONFLICT on (external_app_id, user_id). Raises
    ``OnyxError(NOT_FOUND)`` if the app doesn't exist.
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


def delete_external_app_user_credential(
    db_session: Session,
    *,
    external_app_id: int,
    user_id: UUID,
) -> None:
    """Delete the user's stored credentials for one app, and commit (no-op if
    absent). Used when a refresh terminally fails so the user reconnects."""
    db_session.execute(
        delete(ExternalAppUserCredential).where(
            ExternalAppUserCredential.external_app_id == external_app_id,
            ExternalAppUserCredential.user_id == user_id,
        )
    )
    db_session.commit()
