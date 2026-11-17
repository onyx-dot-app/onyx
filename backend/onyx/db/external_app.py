from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ExternalAppType,
    SkillSharePermission,
)
from onyx.db.models import (
    ExternalApp,
    ExternalAppUserCredential,
    Skill,
)
from onyx.db.utils import UNSET, UnsetType, is_set
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.registry import PROVIDERS
from onyx.skills.built_in import EXTERNAL_APP_BUILT_IN_SKILL_IDS
from onyx.utils.encryption import is_masked_credential
from onyx.utils.logger import setup_logger
from onyx.utils.sensitive import SensitiveValue

logger = setup_logger()


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


def get_external_app_by_id(
    db_session: Session,
    external_app_id: int,
) -> ExternalApp | None:
    return db_session.scalar(
        select(ExternalApp).where(ExternalApp.id == external_app_id)
    )


def get_external_apps(
    db_session: Session,
    *,
    enabled_only: bool = False,
) -> list[ExternalApp]:
    stmt = select(ExternalApp).order_by(ExternalApp.id)
    if enabled_only:
        stmt = stmt.where(ExternalApp.enabled.is_(True))
    return list(db_session.scalars(stmt).all())


def get_built_in_external_app(
    db_session: Session,
    app_type: ExternalAppType,
) -> ExternalApp | None:
    """The tenant's built-in external app of the given type, or None.

    Callers expect at most one configured row for a built-in provider type.
    ``CUSTOM`` is rejected because multiple custom apps may share that type, so
    callers must identify them by ID instead.
    """
    if not app_type.is_built_in:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"get_built_in_external_app requires a built-in app type, got "
            f"'{app_type.value}'.",
        )
    stmt = select(ExternalApp).where(ExternalApp.app_type == app_type)
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
    app_type: ExternalAppType,
    upstream_url_patterns: list[str],
    auth_template: dict[str, Any],
    organization_credentials: dict[str, str],
    enabled: bool = True,
) -> ExternalApp:
    """Create an external-app gateway row.

    Flush only; callers own the transaction. Built-in provisioning separately
    makes its system skill row with ``associate_built_in_skill__no_commit``.
    """
    # No existing app to restore from on create, so a masked value is rejected.
    organization_credentials = resolve_masked_credentials(
        organization_credentials, None
    )
    provider = PROVIDERS.get(app_type)
    if provider is not None:
        upstream_url_patterns = provider.resolve_upstream_url_patterns(
            organization_credentials, upstream_url_patterns
        )
    app = ExternalApp(
        enabled=enabled,
        name=name,
        app_type=app_type,
        upstream_url_patterns=upstream_url_patterns,
        auth_template=auth_template,
        organization_credentials=organization_credentials,
    )
    db_session.add(app)
    db_session.flush()
    return app


def associate_built_in_skill__no_commit(
    db_session: Session,
    app: ExternalApp,
) -> Skill:
    """Create or reuse the provider's built-in skill row for a new app. No row
    links the skill to the app: a user gets the skill through a plugin that
    holds the app's integration (``onyx.db.app_skill``). Refuses a second app
    of one built-in type. Flush only; callers own the transaction.
    """
    from onyx.db.skill import add_new_skill__no_commit

    other_app_id = db_session.scalar(
        select(ExternalApp.id)
        .where(ExternalApp.app_type == app.app_type, ExternalApp.id != app.id)
        .limit(1)
    )
    if other_app_id is not None:
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE,
            f"The built-in app '{app.app_type.value}' is already configured.",
        )

    built_in_skill_id = EXTERNAL_APP_BUILT_IN_SKILL_IDS.get(app.app_type)
    if built_in_skill_id is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Only built-in external apps have a system skill.",
        )

    skill = db_session.scalar(
        select(Skill).where(
            Skill.built_in_skill_id == built_in_skill_id,
            Skill.name == built_in_skill_id,
        )
    )
    if skill is None:
        skill = add_new_skill__no_commit(
            Skill(
                name=built_in_skill_id,
                description="",
                built_in_skill_id=built_in_skill_id,
                bundle_file_id=None,
                bundle_sha256=None,
                is_valid=True,
                public_permission=SkillSharePermission.VIEWER,
            ),
            db_session,
        )

    skill.public_permission = SkillSharePermission.VIEWER
    db_session.flush()
    return skill


def delete_external_app(
    db_session: Session,
    external_app_id: int,
) -> None:
    """Delete an app and the built-in skill row of its preset. Skills of the
    app's plugins stay as they are. Flush only; the caller owns the
    transaction.
    """
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )

    built_in_skill_id = EXTERNAL_APP_BUILT_IN_SKILL_IDS.get(app.app_type)
    db_session.delete(app)
    if built_in_skill_id is not None:
        for skill in db_session.scalars(
            select(Skill).where(Skill.built_in_skill_id == built_in_skill_id)
        ):
            db_session.delete(skill)
    db_session.flush()


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

    stmt = insert(ExternalAppUserCredential).values(
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


def disconnect_external_app_for_user(
    db_session: Session,
    *,
    external_app_id: int,
    user_id: UUID,
) -> None:
    """Remove the user's credentials for the app. Skill choices stay.

    Flush only; the caller refreshes the user's sandbox and commits.
    """
    db_session.execute(
        delete(ExternalAppUserCredential).where(
            ExternalAppUserCredential.external_app_id == external_app_id,
            ExternalAppUserCredential.user_id == user_id,
        )
    )
    db_session.flush()
