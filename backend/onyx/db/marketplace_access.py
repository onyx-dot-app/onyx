"""Marketplace defaults and their database-derived skill grants."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from onyx.auth.scoped_permissions import assert_global, assert_within_scope
from onyx.db.enums import Permission, SkillSharePermission
from onyx.db.models import Marketplace, Marketplace__UserGroup, Skill, User
from onyx.db.resource_access import (
    ResourceAccessAdapter,
    ResourceAccessChange,
    ResourceAccessState,
    lock_resource_access_user,
)
from onyx.db.skill import SkillAccessAdapter, affected_user_ids_for_skills
from onyx.db.skill_mutation import assert_skill_mutable
from onyx.db.user_group import assert_not_shared_with_default_group
from onyx.db.users import lock_group_membership
from onyx.db.utils import is_fk_violation
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.settings.models import Tier
from onyx.utils.variable_functionality import is_ee_available

IS_ENTERPRISE_BUILD = is_ee_available()


def _lock_marketplace(marketplace_id: UUID, db_session: Session) -> Marketplace:
    lock_group_membership(db_session)
    marketplace = db_session.scalar(
        select(Marketplace)
        .where(Marketplace.id == marketplace_id)
        .options(selectinload(Marketplace.group_shares))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if marketplace is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Marketplace not found")
    return marketplace


def _copy_access(
    marketplace: Marketplace,
    skills: Collection[Skill],
    db_session: Session,
    *,
    reset: bool = False,
) -> set[UUID]:
    if marketplace.owner_user_id is not None:
        return set()
    community = not IS_ENTERPRISE_BUILD
    shares = [] if community else marketplace.group_shares
    groups = {share.user_group_id: share.permission for share in shares}
    policies = {share.user_group_id: share.installation_policy for share in shares}
    public = SkillSharePermission.VIEWER if community else marketplace.public_permission
    adapter = SkillAccessAdapter()
    changed: set[UUID] = set()
    for skill in skills:
        current = adapter.state(skill)
        if (
            current.public_permission != public
            or current.group_shares != groups
            or current.group_installation_policies != policies
            or skill.installation_policy != marketplace.installation_policy
            or (reset and current.user_shares)
        ):
            adapter.write(
                skill,
                ResourceAccessChange(
                    public_permission=public,
                    set_public_permission=True,
                    installation_policy=marketplace.installation_policy,
                    user_shares={} if reset else None,
                    group_shares=groups,
                    group_installation_policies=policies,
                ),
                db_session,
            )
            changed.add(skill.id)
        skill.follows_marketplace_access = True
    db_session.flush()
    return changed


def materialize_marketplace_access__no_commit(
    marketplace_id: UUID, db_session: Session
) -> set[UUID]:
    """Copy stored defaults to live company followers; return changed skill ids."""
    marketplace = _lock_marketplace(marketplace_id, db_session)
    if marketplace.owner_user_id is not None:
        return set()
    skills = list(
        db_session.scalars(
            select(Skill)
            .where(
                Skill.marketplace_id == marketplace_id,
                Skill.retired_at.is_(None),
                Skill.follows_marketplace_access.is_(True),
            )
            .order_by(Skill.id)
            .with_for_update(of=Skill)
            .options(selectinload(Skill.user_shares), selectinload(Skill.group_shares))
            .execution_options(populate_existing=True)
        )
    )
    return _copy_access(marketplace, skills, db_session)


class MarketplaceAccessAdapter(ResourceAccessAdapter[Marketplace]):
    permission = Permission.MANAGE_SKILLS

    def __init__(self, tier: Tier) -> None:
        self.tier = tier

    def load(
        self,
        resource_id: UUID,
        user: User,
        db_session: Session,
        *,
        allow_management: bool,
    ) -> Marketplace:
        if not allow_management:
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "API token lacks manage-skills scope.",
            )
        marketplace = _lock_marketplace(resource_id, db_session)
        if marketplace.owner_user_id is not None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Share personal marketplace skills individually.",
            )
        assert_within_scope(
            user,
            db_session,
            permission=self.permission,
            current_group_ids=[
                share.user_group_id for share in marketplace.group_shares
            ],
            requested_group_ids=[],
            is_non_public=marketplace.public_permission is None,
        )
        return marketplace

    def state(self, resource: Marketplace) -> ResourceAccessState:
        return ResourceAccessState(
            owner_user_id=resource.owner_user_id,
            public_permission=resource.public_permission,
            user_shares={},
            group_shares={
                share.user_group_id: share.permission for share in resource.group_shares
            },
            group_installation_policies={
                share.user_group_id: share.installation_policy
                for share in resource.group_shares
            },
        )

    def write(
        self, resource: Marketplace, change: ResourceAccessChange, db_session: Session
    ) -> None:
        if change.user_shares:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Marketplaces use company and group access.",
            )
        community = self.tier == Tier.COMMUNITY
        current = self.state(resource)
        if community and (
            (
                change.group_shares is not None
                and change.group_shares != current.group_shares
            )
            or change.group_installation_policies != current.group_installation_policies
        ):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT, "Group access requires a paid tier."
            )
        if change.set_public_permission:
            if community and change.public_permission != SkillSharePermission.VIEWER:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "Private company access requires a paid tier.",
                )
            resource.public_permission = change.public_permission
        if change.installation_policy is not None:
            resource.installation_policy = change.installation_policy
        if change.group_shares is not None:
            groups = change.group_shares
            assert_not_shared_with_default_group(db_session, list(groups))
            db_session.execute(
                delete(Marketplace__UserGroup).where(
                    Marketplace__UserGroup.marketplace_id == resource.id
                )
            )
            for group_id, permission in groups.items():
                db_session.add(
                    Marketplace__UserGroup(
                        marketplace_id=resource.id,
                        user_group_id=group_id,
                        permission=permission,
                        installation_policy=change.group_installation_policies.get(
                            group_id
                        ),
                    )
                )
            try:
                db_session.flush()
            except IntegrityError as exc:
                if is_fk_violation(exc):
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        "One or more group share targets do not exist.",
                    ) from exc
                raise
            db_session.expire(resource, ["group_shares"])
        db_session.flush()
        materialize_marketplace_access__no_commit(resource.id, db_session)

    def affected_users(
        self, resource_ids: Collection[UUID], db_session: Session
    ) -> dict[UUID, set[UUID]]:
        followers = list(
            db_session.execute(
                select(Skill.id, Skill.marketplace_id).where(
                    Skill.marketplace_id.in_(resource_ids),
                    Skill.retired_at.is_(None),
                    Skill.follows_marketplace_access.is_(True),
                )
            )
        )
        audiences = affected_user_ids_for_skills(
            [skill_id for skill_id, _ in followers], db_session
        )
        result: dict[UUID, set[UUID]] = {}
        for skill_id, marketplace_id in followers:
            if marketplace_id is not None:
                result.setdefault(marketplace_id, set()).update(
                    audiences.get(skill_id, set())
                )
        return result


def reset_marketplace_skill_access__no_commit(
    skill_id: UUID, user: User, db_session: Session
) -> set[UUID]:
    """Clear a company's per-skill overrides; caller commits and pushes recipients."""
    actor = lock_resource_access_user(user.id, db_session)
    assert_global(actor, permission=Permission.MANAGE_SKILLS)
    marketplace_id = db_session.scalar(
        select(Skill.marketplace_id).where(Skill.id == skill_id)
    )
    if marketplace_id is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Skill has no marketplace access to restore."
        )
    with db_session.begin_nested():
        marketplace = _lock_marketplace(marketplace_id, db_session)
        if marketplace.owner_user_id is not None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Personal marketplace skills have individual access.",
            )
        skill = db_session.scalar(
            select(Skill)
            .where(
                Skill.id == skill_id,
                Skill.marketplace_id == marketplace_id,
            )
            .with_for_update(of=Skill)
            .execution_options(populate_existing=True)
        )
        if skill is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
        assert_skill_mutable(skill)
        before = affected_user_ids_for_skills([skill_id], db_session).get(
            skill_id, set()
        )
        _copy_access(marketplace, [skill], db_session, reset=True)
        return before | affected_user_ids_for_skills([skill_id], db_session).get(
            skill_id, set()
        )
