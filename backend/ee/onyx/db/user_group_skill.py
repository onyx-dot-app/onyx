"""Group skill settings: direct Skill shares and company marketplace defaults.

Reads list one row per company marketplace and per direct Skill share. Writes
change one group installation setting through the shared access mutation."""

from collections import defaultdict
from collections.abc import Collection
from uuid import UUID

from sqlalchemy import and_, func, not_, select
from sqlalchemy.orm import Session

from ee.onyx.db.user_group import fetch_user_group
from ee.onyx.server.user_group.models import (
    GroupMarketplaceSetting,
    GroupSkillSetting,
    GroupSkillSource,
    UserGroupSkills,
)
from onyx.auth.permissions import has_global_permission, has_permission
from onyx.auth.scoped_permissions import (
    assert_within_scope,
    get_scoped_groups,
    within_scope,
)
from onyx.db.enums import (
    Permission,
    PermissionAuthority,
    SkillInstallationPolicy,
)
from onyx.db.marketplace_access import MarketplaceAccessAdapter
from onyx.db.models import (
    Marketplace,
    Marketplace__UserGroup,
    Skill,
    Skill__UserGroup,
    User,
)
from onyx.db.resource_access import (
    ResourceAccessChange,
    lock_resource_access_user,
    mutate_resource_access,
)
from onyx.db.skill import SkillAccessAdapter
from onyx.db.skill_mutation import is_company_marketplace_skill
from onyx.db.user_group import assert_group_config_is_editable
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.settings.models import Tier


def _skill_group_ids(
    skill_ids: Collection[UUID], db_session: Session
) -> dict[UUID, set[int]]:
    groups: dict[UUID, set[int]] = defaultdict(set)
    for skill_id, group_id in db_session.execute(
        select(Skill__UserGroup.skill_id, Skill__UserGroup.user_group_id).where(
            Skill__UserGroup.skill_id.in_(skill_ids)
        )
    ):
        groups[skill_id].add(group_id)
    return groups


def list_user_group_skills(
    user_group_id: int,
    user: User,
    db_session: Session,
) -> UserGroupSkills:
    """Caller checks group read authority. Retired Skills and personal
    marketplaces are left out; following company Skills appear only under
    their marketplace. can_edit is a hint; the write path decides."""
    global_skills = has_global_permission(user, Permission.MANAGE_SKILLS)
    scoped = (
        has_permission(user, Permission.MANAGE_SKILLS) is PermissionAuthority.SCOPED
    )
    managed = (
        get_scoped_groups(user, db_session, Permission.MANAGE_SKILLS)
        if scoped
        else set[int]()
    )
    marketplace_groups = (
        select(func.array_agg(Marketplace__UserGroup.user_group_id))
        .where(Marketplace__UserGroup.marketplace_id == Marketplace.id)
        .correlate(Marketplace)
        .scalar_subquery()
    )

    followers = (
        select(func.count(Skill.id))
        .where(
            Skill.marketplace_id == Marketplace.id,
            Skill.retired_at.is_(None),
            Skill.follows_marketplace_access.is_(True),
        )
        .correlate(Marketplace)
        .scalar_subquery()
    )
    marketplaces = [
        GroupMarketplaceSetting(
            marketplace_id=marketplace_id,
            name=name,
            permission=permission,
            company_installation_policy=company_policy,
            group_installation_policy=group_policy,
            effective_installation_policy=group_policy or company_policy,
            following_skill_count=count,
            can_edit=within_scope(
                user,
                db_session,
                permission=Permission.MANAGE_SKILLS,
                current_group_ids=group_ids,
                requested_group_ids=[],
                is_non_public=public_permission is None,
                managed_group_ids=managed,
            ),
        )
        for marketplace_id, name, permission, company_policy, group_policy, count, public_permission, group_ids in (
            db_session.execute(
                select(
                    Marketplace.id,
                    Marketplace.name,
                    Marketplace__UserGroup.permission,
                    Marketplace.installation_policy,
                    Marketplace__UserGroup.installation_policy,
                    followers,
                    Marketplace.public_permission,
                    marketplace_groups,
                )
                .join(
                    Marketplace__UserGroup,
                    Marketplace__UserGroup.marketplace_id == Marketplace.id,
                )
                .where(
                    Marketplace__UserGroup.user_group_id == user_group_id,
                    Marketplace.owner_user_id.is_(None),
                )
                .order_by(func.lower(Marketplace.name), Marketplace.id)
            ).tuples()
        )
    ]

    rows = db_session.execute(
        select(
            Skill.id,
            Skill.name,
            Skill.description,
            Skill.built_in_skill_id,
            Skill.marketplace_id,
            Skill.public_permission,
            Skill.installation_policy,
            Skill__UserGroup.permission,
            Skill__UserGroup.installation_policy,
            Marketplace.name,
            Marketplace.owner_user_id,
        )
        .join(Skill__UserGroup, Skill__UserGroup.skill_id == Skill.id)
        .outerjoin(Marketplace, Marketplace.id == Skill.marketplace_id)
        .where(
            Skill__UserGroup.user_group_id == user_group_id,
            Skill.retired_at.is_(None),
            not_(
                and_(
                    Skill.marketplace_id.is_not(None),
                    Marketplace.owner_user_id.is_(None),
                    Skill.follows_marketplace_access.is_(True),
                )
            ),
        )
        .order_by(func.lower(Skill.name), Skill.id)
    ).all()

    skill_groups = (
        _skill_group_ids([row[0] for row in rows], db_session) if scoped else {}
    )
    skills: list[GroupSkillSetting] = []
    for (
        skill_id,
        name,
        description,
        built_in_skill_id,
        marketplace_id,
        public_permission,
        company_policy,
        permission,
        group_policy,
        marketplace_name,
        marketplace_owner_id,
    ) in rows:
        if built_in_skill_id is not None:
            source = GroupSkillSource.BUILT_IN
        elif marketplace_id is None:
            source = GroupSkillSource.UPLOADED
        elif marketplace_owner_id is None:
            source = GroupSkillSource.COMPANY_MARKETPLACE
        else:
            source = GroupSkillSource.PERSONAL_MARKETPLACE
        skills.append(
            GroupSkillSetting(
                skill_id=skill_id,
                name=name,
                description=description,
                source=source,
                marketplace_id=marketplace_id,
                marketplace_name=marketplace_name,
                permission=permission,
                company_installation_policy=company_policy,
                group_installation_policy=group_policy,
                effective_installation_policy=group_policy or company_policy,
                can_edit=built_in_skill_id is None
                and (
                    global_skills
                    or (
                        scoped
                        and within_scope(
                            user,
                            db_session,
                            permission=Permission.MANAGE_SKILLS,
                            current_group_ids=skill_groups.get(skill_id, set()),
                            requested_group_ids=[],
                            is_non_public=public_permission is None,
                            managed_group_ids=managed,
                        )
                    )
                ),
            )
        )
    return UserGroupSkills(marketplaces=marketplaces, skills=skills)


class GroupSkillAccessAdapter(SkillAccessAdapter):
    """Changes only the Skills that the group list shows as direct rows."""

    def load(
        self,
        resource_id: UUID,
        user: User,
        db_session: Session,
        *,
        allow_management: bool,
    ) -> Skill:
        skill = super().load(
            resource_id, user, db_session, allow_management=allow_management
        )
        if skill.follows_marketplace_access and is_company_marketplace_skill(
            skill, db_session
        ):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "This skill uses its marketplace setting. Change the marketplace instead.",
            )
        return skill


def _lock_group_target(user_group_id: int, user: User, db_session: Session) -> User:
    actor = lock_resource_access_user(user.id, db_session)
    assert_within_scope(
        actor,
        db_session,
        permission=Permission.MANAGE_SKILLS,
        current_group_ids=[user_group_id],
        requested_group_ids=[],
        is_non_public=True,
    )
    if fetch_user_group(db_session, user_group_id) is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "User group not found")
    assert_group_config_is_editable(db_session, user_group_id, "share skills with")
    return actor


def set_group_skill_installation_policy__no_commit(
    user_group_id: int,
    skill_id: UUID,
    installation_policy: SkillInstallationPolicy | None,
    user: User,
    db_session: Session,
) -> set[UUID]:
    """Caller commits, then pushes the returned audience."""
    actor = _lock_group_target(user_group_id, user, db_session)
    return mutate_resource_access(
        [skill_id],
        ResourceAccessChange(
            group_installation_policies={user_group_id: installation_policy}
        ),
        actor,
        db_session,
        GroupSkillAccessAdapter(),
    ).affected


def set_group_marketplace_installation_policy__no_commit(
    user_group_id: int,
    marketplace_id: UUID,
    installation_policy: SkillInstallationPolicy | None,
    user: User,
    db_session: Session,
    *,
    tier: Tier,
) -> set[UUID]:
    """Resolve tier before entering. Caller commits, then pushes the returned audience."""
    actor = _lock_group_target(user_group_id, user, db_session)
    return mutate_resource_access(
        [marketplace_id],
        ResourceAccessChange(
            group_installation_policies={user_group_id: installation_policy}
        ),
        actor,
        db_session,
        MarketplaceAccessAdapter(tier),
    ).affected
