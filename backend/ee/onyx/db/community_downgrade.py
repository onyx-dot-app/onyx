"""Database changes for dropping a self-hosted deployment to the Community tier."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import and_, delete, null, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.document import mark_cc_pair_documents_for_sync__no_commit
from onyx.db.enums import (
    AccessType,
    AccountType,
    Permission,
    PersonaSharePermission,
    SkillSharePermission,
)
from onyx.db.models import (
    ConnectorCredentialPair,
    Credential__UserGroup,
    Document,
    DocumentSet,
    DocumentSet__UserGroup,
    HierarchyNode,
    LLMProvider,
    LLMProvider__UserGroup,
    MCPServer,
    MCPServer__UserGroup,
    PermissionGrant,
    Persona,
    Persona__UserFile,
    Persona__UserGroup,
    PublicExternalUserGroup,
    Skill,
    Skill__UserGroup,
    TokenRateLimit,
    TokenRateLimit__UserGroup,
    User,
    User__ExternalUserGroupId,
    User__UserGroup,
    UserFile,
    UserGroup,
    UserGroup__CCPairDataAccess,
    UserGroup__ConnectorCredentialPair,
)
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.db.users import (
    DEFAULT_ADMIN_GROUP_NAME,
    DEFAULT_BASIC_GROUP_NAME,
    fetch_default_group,
    lock_group_membership,
)

# Link tables whose rows the group row's deletion does not cascade to.
_UNCASCADED_GROUP_LINKS = (
    User__UserGroup,
    UserGroup__ConnectorCredentialPair,
    Persona__UserGroup,
    LLMProvider__UserGroup,
    DocumentSet__UserGroup,
    Credential__UserGroup,
    MCPServer__UserGroup,
    TokenRateLimit__UserGroup,
)


def make_all_cc_pairs_public__no_commit(db_session: Session) -> list[int]:
    """Community has only public connectors, so every other pair becomes one and
    the permissions synced from its source stop applying. Returns the ids of the
    pairs that changed.

    The index keeps the old chunk ACLs until metadata sync has rewritten the
    documents this marks."""
    # Membership lock before the pair rows, the order a connector access edit
    # takes them in, so the two cannot deadlock.
    lock_group_membership(db_session)
    # Id order and a key-share lock, like every other locker of these rows: no
    # deadlock with them, and inserts that reference a pair are not blocked.
    cc_pair_ids: list[int] = list(
        db_session.scalars(
            select(ConnectorCredentialPair.id)
            .where(ConnectorCredentialPair.access_type != AccessType.PUBLIC)
            .order_by(ConnectorCredentialPair.id)
            .with_for_update(key_share=True)
        )
    )
    if cc_pair_ids:
        db_session.execute(
            update(ConnectorCredentialPair)
            .where(ConnectorCredentialPair.id.in_(cc_pair_ids))
            .values(
                access_type=AccessType.PUBLIC,
                # null(): a plain None would store a JSON null in the JSONB column.
                auto_sync_options=null(),
                last_time_perm_sync=None,
                last_time_external_group_sync=None,
            )
        )
        mark_cc_pair_documents_for_sync__no_commit(db_session, cc_pair_ids)

    # Not scoped to the changed pairs: with every pair public, nothing may keep a
    # data-access group or a synced permission, whichever pair wrote it. A sync
    # already in flight can still write some back, which grants nothing on a public pair.
    db_session.execute(delete(UserGroup__CCPairDataAccess))
    db_session.execute(delete(User__ExternalUserGroupId))
    db_session.execute(delete(PublicExternalUserGroup))
    db_session.execute(
        update(Document)
        .where(
            or_(
                Document.external_user_emails.is_not(None),
                Document.external_user_group_ids.is_not(None),
                Document.is_public.is_(True),
            )
        )
        .values(
            external_user_emails=None,
            external_user_group_ids=None,
            is_public=False,
        )
    )
    # is_public stays: a node is readable through its now-public pair, and the
    # next indexing run of a public pair sets it.
    db_session.execute(
        update(HierarchyNode)
        .where(
            or_(
                HierarchyNode.external_user_emails.is_not(None),
                HierarchyNode.external_user_group_ids.is_not(None),
            )
        )
        .values(external_user_emails=None, external_user_group_ids=None)
    )
    return cc_pair_ids


def _make_group_shared_resources_public__no_commit(
    db_session: Session, group_ids: list[int]
) -> None:
    """Whatever these groups can read becomes readable by everyone, so removing
    the groups takes no read access away. Edit rights a group share gave go
    with the group."""
    shared_persona_ids = select(Persona__UserGroup.persona_id).where(
        Persona__UserGroup.user_group_id.in_(group_ids)
    )
    # A group's members read a persona shared with the group or owned by it.
    newly_public_persona = and_(
        or_(
            Persona.id.in_(shared_persona_ids),
            Persona.owner_group_id.in_(group_ids),
        ),
        Persona.is_public.is_(False),
    )
    # A persona's files carry its access in the index, so they need a sync.
    db_session.execute(
        update(UserFile)
        .where(
            UserFile.id.in_(
                select(Persona__UserFile.user_file_id)
                .join(Persona, Persona.id == Persona__UserFile.persona_id)
                .where(newly_public_persona)
            )
        )
        .values(needs_persona_sync=True)
    )
    db_session.execute(
        update(Persona)
        .where(newly_public_persona)
        # A private persona can hold a stale EDITOR here, which would make it
        # editable by the whole org the moment it turns public.
        .values(is_public=True, public_permission=PersonaSharePermission.VIEWER)
    )
    db_session.execute(
        update(DocumentSet)
        .where(
            DocumentSet.id.in_(
                select(DocumentSet__UserGroup.document_set_id).where(
                    DocumentSet__UserGroup.user_group_id.in_(group_ids)
                )
            )
        )
        .values(is_public=True)
    )
    db_session.execute(
        update(LLMProvider)
        .where(
            LLMProvider.id.in_(
                select(LLMProvider__UserGroup.llm_provider_id).where(
                    LLMProvider__UserGroup.user_group_id.in_(group_ids)
                )
            )
        )
        .values(is_public=True)
    )
    db_session.execute(
        update(MCPServer)
        .where(
            MCPServer.id.in_(
                select(MCPServer__UserGroup.mcp_server_id).where(
                    MCPServer__UserGroup.user_group_id.in_(group_ids)
                )
            )
        )
        .values(is_public=True)
    )
    db_session.execute(
        update(Skill)
        .where(
            Skill.id.in_(
                select(Skill__UserGroup.skill_id).where(
                    Skill__UserGroup.user_group_id.in_(group_ids)
                )
            ),
            Skill.public_permission.is_(None),
        )
        .values(public_permission=SkillSharePermission.VIEWER)
    )


def _add_to_default_group__no_commit(
    db_session: Session, group_name: str, user_ids: Sequence[UUID]
) -> None:
    if not user_ids:
        return
    group_id = fetch_default_group(db_session, group_name).id
    db_session.execute(
        pg_insert(User__UserGroup)
        .values(
            [{"user_id": user_id, "user_group_id": group_id} for user_id in user_ids]
        )
        .on_conflict_do_nothing()
    )


def _keep_members_in_default_groups__no_commit(
    db_session: Session, group_ids: list[int], member_ids: list[UUID]
) -> None:
    """Permissions come only from group grants. Whoever is an admin through one
    of these groups joins Admin, so the workspace keeps its admins and its admin
    API keys, and a standard user left in no default group joins Basic."""
    user_id = User.__table__.c.id
    is_standard = User.account_type == AccountType.STANDARD
    # The account types that take their permissions from groups.
    in_group_system = User.account_type.in_(
        (AccountType.STANDARD, AccountType.SERVICE_ACCOUNT)
    )
    admin_ids: Sequence[UUID] = db_session.scalars(
        select(user_id)
        .join(User__UserGroup, User__UserGroup.user_id == user_id)
        .join(
            PermissionGrant,
            PermissionGrant.group_id == User__UserGroup.user_group_id,
        )
        .where(
            User__UserGroup.user_group_id.in_(group_ids),
            PermissionGrant.permission == Permission.FULL_ADMIN_PANEL_ACCESS,
            PermissionGrant.is_deleted.is_(False),
            in_group_system,
        )
        .distinct()
    ).all()
    _add_to_default_group__no_commit(db_session, DEFAULT_ADMIN_GROUP_NAME, admin_ids)

    in_default_group = (
        select(User__UserGroup.user_id)
        .join(UserGroup, UserGroup.id == User__UserGroup.user_group_id)
        .where(User__UserGroup.user_id == user_id, UserGroup.is_default.is_(True))
        .exists()
    )
    stranded_ids: Sequence[UUID] = db_session.scalars(
        select(user_id).where(user_id.in_(member_ids), is_standard, ~in_default_group)
    ).all()
    _add_to_default_group__no_commit(db_session, DEFAULT_BASIC_GROUP_NAME, stranded_ids)


def remove_custom_user_groups__no_commit(db_session: Session) -> int:
    """Groups are a paid feature, so every group but the default ones is removed.
    Nobody loses read access or full admin rights by it, and other group grants
    go with the group. Returns how many groups were removed.

    Deletes the rows directly instead of scheduling the group sync: with their
    resources public and every connector already public, the groups gate
    nothing a sync would need to rewrite."""
    lock_group_membership(db_session)
    # No row lock here: a share edit locks its resource and then the group, so
    # the groups are locked last too, by their delete.
    group_ids: list[int] = list(
        db_session.scalars(select(UserGroup.id).where(UserGroup.is_default.is_(False)))
    )
    if not group_ids:
        return 0

    _make_group_shared_resources_public__no_commit(db_session, group_ids)

    member_ids: list[UUID] = [
        member_id
        for member_id in db_session.scalars(
            select(User__UserGroup.user_id)
            .where(User__UserGroup.user_group_id.in_(group_ids))
            .distinct()
        )
        if member_id is not None
    ]
    _keep_members_in_default_groups__no_commit(db_session, group_ids, member_ids)

    # A group's limit means nothing without the group.
    group_rate_limit_ids: list[int] = list(
        db_session.scalars(
            select(TokenRateLimit__UserGroup.rate_limit_id).where(
                TokenRateLimit__UserGroup.user_group_id.in_(group_ids)
            )
        )
    )
    for link in _UNCASCADED_GROUP_LINKS:
        db_session.execute(delete(link).where(link.user_group_id.in_(group_ids)))
    db_session.execute(
        delete(TokenRateLimit).where(TokenRateLimit.id.in_(group_rate_limit_ids))
    )
    db_session.execute(delete(UserGroup).where(UserGroup.id.in_(group_ids)))

    recompute_user_permissions__no_commit(member_ids, db_session)
    return len(group_ids)
