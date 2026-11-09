"""Management transactions. Callers validate providers first, commit, then dispatch/push."""

from uuid import UUID

from sqlalchemy import delete, exists, func, select
from sqlalchemy.orm import Session, defer, selectinload

from onyx.auth.permissions import has_global_permission
from onyx.auth.scoped_permissions import assert_global
from onyx.db import marketplace_access
from onyx.db.enums import ExternalAppType, Permission, SkillSharePermission
from onyx.db.marketplace_access import MarketplaceAccessAdapter
from onyx.db.marketplace_sync import request_marketplace_sync__no_commit
from onyx.db.models import (
    ExternalApp,
    ExternalAppUserCredential,
    Marketplace,
    Skill,
    User,
)
from onyx.db.resource_access import (
    ResourceAccessChange,
    fetch_resource_access_user,
    lock_resource_access_user,
    mutate_resource_access,
)
from onyx.db.skill import affected_user_ids_for_skills
from onyx.db.skill_version import skill_bundle_file_ids_for_skills
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.settings.models import Tier
from onyx.skills.marketplace.models import (
    MARKETPLACE_LOGIN_ERROR,
    GitHubMarketplaceConfig,
    MarketplaceManagedSkill,
    MarketplaceManagementDetail,
    MarketplaceManagementSnapshot,
    MarketplaceProvider,
    MarketplaceRemovalResult,
)


def _lock_managed_marketplace(
    marketplace_id: UUID,
    user: User,
    db_session: Session,
    *,
    global_personal: bool = False,
) -> Marketplace:
    actor = lock_resource_access_user(user.id, db_session)
    row = db_session.scalar(
        select(Marketplace)
        .where(Marketplace.id == marketplace_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Marketplace not found")
    if row.owner_user_id != actor.id:
        if row.owner_user_id is not None and not global_personal:
            raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)
        assert_global(actor, permission=Permission.MANAGE_SKILLS)
    return row


def _assert_connected_login(
    user_id: UUID | None, provider: MarketplaceProvider, db_session: Session
) -> None:
    # Check stored facts after provider I/O, without loading or refreshing secrets.
    if provider != MarketplaceProvider.GITHUB or not db_session.scalar(
        select(
            exists().where(
                ExternalAppUserCredential.user_id == user_id,
                ExternalAppUserCredential.external_app_id == ExternalApp.id,
                ExternalApp.app_type == ExternalAppType.GITHUB,
                ExternalApp.enabled.is_(True),
                ExternalAppUserCredential.user_id == User.id,
                User.__table__.c.is_active.is_(True),
            )
        )
    ):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, MARKETPLACE_LOGIN_ERROR)


def _management_snapshots(
    rows: list[Marketplace], db_session: Session
) -> list[MarketplaceManagementSnapshot]:
    counts = {
        marketplace_id: (live, retired)
        for marketplace_id, live, retired in db_session.execute(
            select(
                Skill.marketplace_id,
                func.count().filter(Skill.retired_at.is_(None)),
                func.count().filter(Skill.retired_at.is_not(None)),
            )
            .where(Skill.marketplace_id.in_([row.id for row in rows]))
            .group_by(Skill.marketplace_id)
        )
    }
    result = []
    for row in rows:
        snapshot = MarketplaceManagementSnapshot.model_validate(row)
        snapshot.sync_pending = row.sync_requested or row.sync_owner is not None
        snapshot.live_skill_count, snapshot.retired_skill_count = counts.get(
            row.id, (0, 0)
        )
        result.append(snapshot)
    return result


def list_managed_marketplaces(
    user: User, db_session: Session
) -> list[MarketplaceManagementSnapshot]:
    actor = fetch_resource_access_user(user.id, db_session)
    query = select(Marketplace)
    if not has_global_permission(actor, Permission.MANAGE_SKILLS):
        query = query.where(Marketplace.owner_user_id == actor.id)
    rows = list(
        db_session.scalars(
            query.options(
                defer(Marketplace.webhook_secret, raiseload=True),
                selectinload(Marketplace.group_shares),
            )
            .order_by(Marketplace.name, Marketplace.id)
            .execution_options(populate_existing=True)
        )
    )
    return _management_snapshots(rows, db_session)


def fetch_managed_marketplace(
    marketplace_id: UUID, user: User, db_session: Session
) -> MarketplaceManagementDetail:
    actor = fetch_resource_access_user(user.id, db_session)
    query = select(Marketplace).where(Marketplace.id == marketplace_id)
    if not has_global_permission(actor, Permission.MANAGE_SKILLS):
        query = query.where(Marketplace.owner_user_id == actor.id)
    row = db_session.scalar(
        query.options(
            defer(Marketplace.webhook_secret, raiseload=True),
            selectinload(Marketplace.group_shares),
        ).execution_options(populate_existing=True)
    )
    if row is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Marketplace not found")
    skills = db_session.scalars(
        select(Skill)
        .where(Skill.marketplace_id == marketplace_id)
        .order_by(Skill.name, Skill.id)
        .execution_options(populate_existing=True)
    )
    return MarketplaceManagementDetail(
        marketplace=_management_snapshots([row], db_session)[0],
        skills=[MarketplaceManagedSkill.model_validate(skill) for skill in skills],
    )


def create_marketplace__no_commit(
    *,
    name: str,
    provider: MarketplaceProvider,
    config: GitHubMarketplaceConfig,
    personal: bool,
    user: User,
    db_session: Session,
) -> Marketplace:
    """Caller validates the source and connected identity before entering this function."""
    actor = lock_resource_access_user(user.id, db_session)
    if not personal:
        assert_global(actor, permission=Permission.MANAGE_SKILLS)
    _assert_connected_login(actor.id, provider, db_session)
    row = Marketplace(
        name=name,
        provider=provider,
        provider_config=config,
        owner_user_id=actor.id if personal else None,
        login_user_id=actor.id,
        public_permission=(
            SkillSharePermission.VIEWER
            if not personal and not marketplace_access.IS_ENTERPRISE_BUILD
            else None
        ),
    )
    db_session.add(row)
    db_session.flush()
    request_marketplace_sync__no_commit(row.id, db_session)
    return row


def request_managed_marketplace_sync__no_commit(
    marketplace_id: UUID, user: User, db_session: Session
) -> None:
    row = _lock_managed_marketplace(
        marketplace_id, user, db_session, global_personal=True
    )
    _assert_connected_login(row.login_user_id, row.provider, db_session)
    request_marketplace_sync__no_commit(row.id, db_session)


def replace_marketplace_login__no_commit(
    marketplace_id: UUID, user: User, db_session: Session
) -> None:
    """Use only the actor's prevalidated connected identity; fence older staged work."""
    row = _lock_managed_marketplace(
        marketplace_id, user, db_session, global_personal=True
    )
    _assert_connected_login(user.id, row.provider, db_session)
    row.login_user_id = user.id
    row.sync_owner = None
    row.sync_lease_expires_at = row.sync_started_at = None
    row.retirement_proposal = None
    row.sync_status = None
    row.last_error = None
    db_session.flush()
    request_marketplace_sync__no_commit(row.id, db_session)


def set_marketplace_default_access__no_commit(
    marketplace_id: UUID,
    change: ResourceAccessChange,
    user: User,
    db_session: Session,
    *,
    tier: Tier,
) -> set[UUID]:
    """Resolve tier before entering. Caller commits, then pushes the returned audience."""
    actor = lock_resource_access_user(user.id, db_session)
    assert_global(actor, permission=Permission.MANAGE_SKILLS)
    return mutate_resource_access(
        [marketplace_id], change, actor, db_session, MarketplaceAccessAdapter(tier)
    ).affected


def remove_marketplace__no_commit(
    marketplace_id: UUID, user: User, db_session: Session
) -> MarketplaceRemovalResult:
    row = _lock_managed_marketplace(
        marketplace_id, user, db_session, global_personal=True
    )
    skills = list(
        db_session.scalars(
            select(Skill)
            .where(Skill.marketplace_id == row.id)
            .order_by(Skill.id)
            .with_for_update(of=Skill)
            .execution_options(populate_existing=True)
        )
    )
    audiences = affected_user_ids_for_skills([skill.id for skill in skills], db_session)
    result = MarketplaceRemovalResult(
        cleanup_file_ids=skill_bundle_file_ids_for_skills(skills, db_session),
        affected_user_ids=set().union(*audiences.values()),
    )
    db_session.execute(delete(Marketplace).where(Marketplace.id == row.id))
    return result
