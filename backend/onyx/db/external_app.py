import re
from typing import Any
from typing import cast
from uuid import UUID
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppPolicy
from onyx.db.models import ExternalAppUserCredential
from onyx.db.models import User
from onyx.db.utils import is_set
from onyx.db.utils import UNSET
from onyx.db.utils import UnsetType
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


def get_external_app_by_skill_id(
    db_session: Session,
    skill_id: UUID,
) -> ExternalApp | None:
    """The external-app gateway backing ``skill_id``, or None if the skill isn't
    an external app. Returns just the row — callers that need its policies fetch
    them via ``get_policies``."""
    stmt = select(ExternalApp).where(ExternalApp.skill_id == skill_id)
    return db_session.scalar(stmt)


def get_connectable_apps_for_user(
    db_session: Session,
    user: User,
) -> list[ExternalApp]:
    """Apps the user could connect but hasn't: enabled, visible to them (public /
    group-granted / personal), requiring per-user credentials the org hasn't
    pre-filled, with no complete credential row yet.

    Apps whose skill the user can't see are excluded — they'd never be injected
    even once connected. Org-credentialed apps (no user-required keys) are usable
    by everyone, so there's nothing to set up."""
    # Local import breaks the external_app <-> skill module cycle.
    from onyx.db.skill import all_skills_for_user_incl_external_apps

    visible_skill_ids = all_skills_for_user_incl_external_apps(user, db_session)
    user_creds_by_app = get_user_credentials_by_app_id(db_session, user.id)
    return [
        app
        for app in get_external_apps(db_session)
        if app.skill_id in visible_skill_ids
        and not is_user_authenticated_for_app(app, user_creds_by_app.get(app.id))
    ]


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


def get_built_in_external_app(
    db_session: Session,
    app_type: ExternalAppType,
) -> ExternalApp | None:
    """The tenant's built-in external app of the given type, or None.

    Built-in apps are unique per type per tenant (enforced via the built-in
    skill slug — see ``create_built_in_skill_row__no_commit``), so at most one
    row matches. ``CUSTOM`` is rejected: it can repeat, so "the app of this
    type" is meaningless — callers must pass a built-in type.
    """
    if not app_type.is_built_in:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"get_built_in_external_app requires a built-in app type, got "
            f"'{app_type.value}'.",
        )
    stmt = (
        select(ExternalApp)
        .options(
            selectinload(ExternalApp.skill),
            selectinload(ExternalApp.policies),
        )
        .where(ExternalApp.app_type == app_type)
    )
    return db_session.scalars(stmt).one_or_none()


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
    """Create the backing Skill row and the ExternalApp that references it (flush
    only — the caller commits after pushing, so a push failure rolls back). The
    skill owns display metadata + lifecycle; the external_app owns gateway state.

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
        _write_policies__no_commit(db_session, app, action_policies)
    db_session.flush()
    return app


def update_external_app(
    db_session: Session,
    external_app_id: int,
    app_type: ExternalAppType,
    name: str | UnsetType = UNSET,
    description: str | UnsetType = UNSET,
    enabled: bool | UnsetType = UNSET,
    upstream_url_patterns: list[str] | UnsetType = UNSET,
    auth_template: dict[str, Any] | UnsetType = UNSET,
    organization_credentials: dict[str, str] | UnsetType = UNSET,
    new_bundle_file_id: str | None = None,
    new_bundle_sha256: str | None = None,
    action_policies: dict[str, EndpointPolicy] | UnsetType = UNSET,
) -> tuple[ExternalApp, str | None]:
    """Partial-update the external app and its linked skill (flush only — the
    caller commits after pushing, so a push failure rolls back). Returns
    ``(app, old_bundle_file_id)``.

    Patch fields default to ``UNSET`` (left untouched); pass a value to set one.
    ``app_type`` is required and immutable — a mismatch raises, blocking
    cross-editing built-in vs custom. Passing ``new_bundle_file_id`` swaps the
    bundle (slug unchanged) and returns the previous blob id for post-commit
    cleanup, else ``None``.

    Raises ``OnyxError(NOT_FOUND)`` if absent, or ``INVALID_INPUT`` on app_type
    mismatch.
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

    if is_set(name):
        app.skill.name = name
    if is_set(description):
        app.skill.description = description
    if is_set(enabled):
        app.skill.enabled = enabled

    old_bundle_file_id: str | None = None
    if new_bundle_file_id is not None:
        # Keep the slug; only the bundle bytes change.
        old_bundle_file_id = app.skill.bundle_file_id
        app.skill.bundle_file_id = new_bundle_file_id
        app.skill.bundle_sha256 = new_bundle_sha256

    if is_set(upstream_url_patterns):
        app.upstream_url_patterns = upstream_url_patterns
    if is_set(auth_template):
        app.auth_template = auth_template
    if is_set(organization_credentials):
        # Admin responses mask org credentials; restore any masked value the form
        # echoed back so an unchanged secret isn't overwritten with its mask.
        app.organization_credentials = resolve_masked_credentials(  # ty: ignore[invalid-assignment]
            organization_credentials, app.organization_credentials
        )

    if is_set(action_policies):
        _write_policies__no_commit(db_session, app, action_policies)

    db_session.flush()
    return app, old_bundle_file_id


def set_external_app_organization_credentials(
    db_session: Session,
    app: ExternalApp,
    organization_credentials: dict[str, str],
) -> None:
    """Replace an app's organization credentials (flush only — the caller
    commits). Used by the Onyx-managed provisioning/rotation path — deliberately
    touches nothing else (enabled state, policies, gateway config are left
    untouched)."""
    # EncryptedJson column accepts a plain dict and encrypts on write (same
    # assignment shape as update_external_app's masked-credential restore).
    app.organization_credentials = organization_credentials  # ty: ignore[invalid-assignment]
    db_session.flush()


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
    app: ExternalApp,
    policies: dict[str, EndpointPolicy],
) -> None:
    """Replace ``app``'s per-action policy rows with exactly ``policies``.

    Clears the existing rows and flushes the DELETEs before inserting the new
    set. The flush is required: within a single flush the ORM emits INSERTs
    before DELETEs, so a re-inserted ``action_id`` would collide with its
    not-yet-deleted row on the ``(external_app_id, action_id)`` unique
    constraint. No commit — runs inside the caller's transaction. ``action_id``
    validation is the caller's responsibility.
    """
    app.policies.clear()  # delete-orphan cascade deletes the rows on flush
    db_session.flush()
    for action_id, policy in policies.items():
        app.policies.append(ExternalAppPolicy(action_id=action_id, policy=policy))


def delete_external_app(
    db_session: Session,
    external_app_id: int,
) -> str | None:
    """Delete the linked Skill (cascade removes the external_app row and user
    credentials). Flush only — the caller commits after pushing, so a push
    failure rolls back. Returns the skill's ``bundle_file_id`` for post-commit
    FileStore cleanup. Raises ``OnyxError(NOT_FOUND)`` if absent.
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


def upsert_external_app_user_credential(
    db_session: Session,
    external_app_id: int,
    user_id: UUID,
    user_credentials: dict[str, Any],
    granted_scopes: list[str] | None | UnsetType = UNSET,
    resolve_masked_values: bool = False,
) -> ExternalAppUserCredential:
    """Create or replace the calling user's credentials for the app, and commit.
    Atomic via ON CONFLICT on (external_app_id, user_id). Raises
    ``OnyxError(NOT_FOUND)`` if the app doesn't exist. ``resolve_masked_values``
    is for user form submissions that may echo masked display values; internal
    OAuth writers should store provider-returned values as-is.

    ``granted_scopes`` is the connect-time OAuth grant: a list, or ``None`` when
    a fresh authorize couldn't determine it — both overwrite the stored value
    (``None`` clears a now-stale grant to "unknown"). The refresh and form paths
    leave it ``UNSET`` to keep the stored grant untouched.
    """
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )

    if resolve_masked_values:
        existing_credential = get_external_app_user_credential(
            db_session,
            external_app_id=external_app_id,
            user_id=user_id,
        )
        user_credentials = resolve_masked_credentials(
            cast(dict[str, str], user_credentials),
            existing_credential.user_credentials
            if existing_credential is not None
            else None,
        )

    stmt = pg_insert(ExternalAppUserCredential).values(
        external_app_id=external_app_id,
        user_id=user_id,
        user_credentials=user_credentials,
        granted_scopes=granted_scopes if is_set(granted_scopes) else None,
    )
    # ON CONFLICT DO UPDATE doesn't fire the column's `onupdate`, so bump
    # `updated_at` explicitly.
    update_set: dict[str, Any] = {
        "user_credentials": stmt.excluded.user_credentials,
        "updated_at": func.now(),
    }
    if is_set(granted_scopes):
        update_set["granted_scopes"] = stmt.excluded.granted_scopes
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            ExternalAppUserCredential.external_app_id,
            ExternalAppUserCredential.user_id,
        ],
        set_=update_set,
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
