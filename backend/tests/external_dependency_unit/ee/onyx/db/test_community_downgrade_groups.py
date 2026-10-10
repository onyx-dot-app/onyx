"""A downgrade to Community removes every custom user group without taking
access away: what a group shared becomes public and its members keep a group.
Each test rolls its transaction back."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.db.community_downgrade import (
    _UNCASCADED_GROUP_LINKS,
    remove_custom_user_groups__no_commit,
)
from onyx.configs.constants import TokenRateLimitScope
from onyx.db.enums import (
    AccountType,
    GrantSource,
    Permission,
    PersonaSharePermission,
    SkillSharePermission,
    UserFileStatus,
)
from onyx.db.models import (
    Base,
    DocumentSet,
    DocumentSet__UserGroup,
    LLMProvider,
    LLMProvider__UserGroup,
    MCPServer,
    MCPServer__UserGroup,
    PermissionGrant,
    Persona,
    Persona__UserFile,
    Persona__UserGroup,
    Skill,
    Skill__UserGroup,
    TokenRateLimit,
    TokenRateLimit__UserGroup,
    User,
    User__UserGroup,
    UserFile,
    UserGroup,
)
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.db.users import (
    DEFAULT_ADMIN_GROUP_NAME,
    DEFAULT_BASIC_GROUP_NAME,
    assign_user_to_default_groups__no_commit,
    fetch_default_group,
)


def test_every_uncascaded_group_link_is_deleted_by_hand() -> None:
    """A link table missing from the list would fail the group delete on its
    foreign key."""
    uncascaded = {
        table.name
        for table in Base.metadata.tables.values()
        for foreign_key in table.foreign_keys
        if foreign_key.column.table.name == "user_group"
        and foreign_key.ondelete is None
    }
    assert {link.__tablename__ for link in _UNCASCADED_GROUP_LINKS} == uncascaded


def _make_user(
    db_session: Session,
    in_basic: bool,
    account_type: AccountType = AccountType.STANDARD,
) -> User:
    user = User(
        id=uuid4(),
        email=f"downgrade-{uuid4().hex[:8]}@example.com",
        hashed_password="unused",
        is_active=True,
        is_superuser=False,
        is_verified=True,
        account_type=account_type,
    )
    db_session.add(user)
    db_session.flush()
    if in_basic:
        assign_user_to_default_groups__no_commit(db_session, user)
    return user


def _make_group(db_session: Session, members: list[User]) -> UserGroup:
    group = UserGroup(name=f"downgrade-{uuid4().hex[:8]}")
    db_session.add(group)
    db_session.flush()
    db_session.add_all(
        User__UserGroup(user_group_id=group.id, user_id=member.id, is_manager=True)
        for member in members
    )
    db_session.flush()
    return group


def _make_private_persona(db_session: Session, owner: User) -> Persona:
    persona = Persona(
        name=f"downgrade-{uuid4().hex[:8]}",
        description="",
        user_id=owner.id,
        is_public=False,
        system_prompt="",
        task_prompt="",
        datetime_aware=True,
        builtin_persona=False,
        is_listed=True,
    )
    db_session.add(persona)
    db_session.flush()
    return persona


def _group_ids_of(db_session: Session, user_id: UUID) -> set[int]:
    return set(
        db_session.scalars(
            select(User__UserGroup.user_group_id).where(
                User__UserGroup.user_id == user_id
            )
        )
    )


@pytest.mark.usefixtures("tenant_context")
def test_groups_are_removed_and_members_keep_a_group(db_session: Session) -> None:
    try:
        basic_group_id = fetch_default_group(db_session, DEFAULT_BASIC_GROUP_NAME).id
        basic_member = _make_user(db_session, in_basic=True)
        custom_only_member = _make_user(db_session, in_basic=False)
        # An API key's service account that is only in the custom group.
        custom_only_key = _make_user(
            db_session, in_basic=False, account_type=AccountType.SERVICE_ACCOUNT
        )
        group = _make_group(
            db_session, [basic_member, custom_only_member, custom_only_key]
        )
        group_id = group.id
        rate_limit = TokenRateLimit(
            token_budget=1, period_hours=1, scope=TokenRateLimitScope.USER_GROUP
        )
        db_session.add(rate_limit)
        db_session.flush()
        rate_limit_id = rate_limit.id
        recompute_user_permissions__no_commit(
            [basic_member.id, custom_only_member.id], db_session
        )
        db_session.refresh(basic_member)
        assert basic_member.is_group_manager
        db_session.add(
            TokenRateLimit__UserGroup(
                rate_limit_id=rate_limit_id, user_group_id=group_id
            )
        )
        db_session.flush()

        removed = remove_custom_user_groups__no_commit(db_session)

        assert removed >= 1
        db_session.expire_all()
        assert not db_session.scalars(
            select(UserGroup.id).where(UserGroup.is_default.is_(False))
        ).all()
        assert _group_ids_of(db_session, basic_member.id) == {basic_group_id}
        assert _group_ids_of(db_session, custom_only_member.id) == {basic_group_id}
        assert _group_ids_of(db_session, custom_only_key.id) == {basic_group_id}
        assert not db_session.scalars(
            select(TokenRateLimit.id).where(TokenRateLimit.id == rate_limit_id)
        ).all()
        # Permissions are recomputed from the groups that are left.
        for member in (basic_member, custom_only_member):
            db_session.refresh(member)
            assert not member.is_group_manager
        assert (
            custom_only_member.effective_permissions
            == basic_member.effective_permissions
        )
    finally:
        db_session.rollback()


# An API key's service account takes its admin rights from groups too.
@pytest.mark.parametrize(
    "account_type", [AccountType.STANDARD, AccountType.SERVICE_ACCOUNT]
)
@pytest.mark.usefixtures("tenant_context")
def test_an_admin_through_a_custom_group_stays_admin(
    db_session: Session, account_type: AccountType
) -> None:
    try:
        admin_group_id = fetch_default_group(db_session, DEFAULT_ADMIN_GROUP_NAME).id
        admin = _make_user(
            db_session,
            in_basic=account_type == AccountType.STANDARD,
            account_type=account_type,
        )
        group = _make_group(db_session, [admin])
        db_session.add(
            PermissionGrant(
                group_id=group.id,
                permission=Permission.FULL_ADMIN_PANEL_ACCESS,
                grant_source=GrantSource.USER,
            )
        )
        db_session.flush()

        remove_custom_user_groups__no_commit(db_session)

        assert admin_group_id in _group_ids_of(db_session, admin.id)
        db_session.refresh(admin)
        assert Permission.FULL_ADMIN_PANEL_ACCESS.value in admin.effective_permissions
    finally:
        db_session.rollback()


@pytest.mark.usefixtures("tenant_context")
def test_what_a_group_shared_becomes_public(db_session: Session) -> None:
    try:
        owner = _make_user(db_session, in_basic=True)
        group = _make_group(db_session, [owner])
        shared_persona = _make_private_persona(db_session, owner)
        shared_persona.public_permission = PersonaSharePermission.EDITOR
        unshared_persona = _make_private_persona(db_session, owner)
        # Owned by the group, with no share row: its members read it as owners.
        owned_persona = _make_private_persona(db_session, owner)
        owned_persona.user_id = None
        owned_persona.owner_group_id = group.id
        owned_file = UserFile(
            id=uuid4(),
            user_id=owner.id,
            file_id=f"downgrade-{uuid4().hex[:8]}",
            name="owned.txt",
            file_type="text/plain",
            status=UserFileStatus.COMPLETED,
            needs_persona_sync=False,
        )
        document_set = DocumentSet(name=f"downgrade-{uuid4().hex[:8]}", is_public=False)
        user_file = UserFile(
            id=uuid4(),
            user_id=owner.id,
            file_id=f"downgrade-{uuid4().hex[:8]}",
            name="notes.txt",
            file_type="text/plain",
            status=UserFileStatus.COMPLETED,
            needs_persona_sync=False,
        )
        db_session.add_all([document_set, user_file, owned_file])
        db_session.flush()
        db_session.add_all(
            [
                Persona__UserGroup(
                    persona_id=shared_persona.id, user_group_id=group.id
                ),
                Persona__UserFile(
                    persona_id=shared_persona.id, user_file_id=user_file.id
                ),
                Persona__UserFile(
                    persona_id=owned_persona.id, user_file_id=owned_file.id
                ),
                DocumentSet__UserGroup(
                    document_set_id=document_set.id, user_group_id=group.id
                ),
            ]
        )
        db_session.flush()

        remove_custom_user_groups__no_commit(db_session)

        for row in (
            shared_persona,
            unshared_persona,
            owned_persona,
            document_set,
            user_file,
            owned_file,
        ):
            db_session.refresh(row)
        assert shared_persona.is_public
        assert owned_persona.is_public
        assert owned_persona.public_permission == PersonaSharePermission.VIEWER
        assert owned_file.needs_persona_sync
        # Public means readable, never editable by the whole org.
        assert shared_persona.public_permission == PersonaSharePermission.VIEWER
        assert document_set.is_public
        # The file's index ACL follows its persona.
        assert user_file.needs_persona_sync
        assert not unshared_persona.is_public
    finally:
        db_session.rollback()


def _make_skill(db_session: Session, author: User) -> Skill:
    skill = Skill(
        id=uuid4(),
        name=f"downgrade-{uuid4().hex[:8]}",
        description="",
        bundle_file_id=f"downgrade-{uuid4().hex[:8]}",
        bundle_sha256="0" * 64,
        public_permission=None,
        author_user_id=author.id,
    )
    db_session.add(skill)
    return skill


@pytest.mark.usefixtures("tenant_context")
def test_group_shared_providers_servers_and_skills_become_public(
    db_session: Session,
) -> None:
    try:
        owner = _make_user(db_session, in_basic=True)
        group = _make_group(db_session, [owner])
        providers = [
            LLMProvider(
                name=f"downgrade-{uuid4().hex[:8]}", provider="openai", is_public=False
            )
            for _ in range(2)
        ]
        servers = [
            MCPServer(
                owner=owner.email,
                name=f"downgrade-{uuid4().hex[:8]}",
                server_url="https://example.com/mcp",
                is_public=False,
            )
            for _ in range(2)
        ]
        skills = [_make_skill(db_session, owner) for _ in range(2)]
        db_session.add_all([*providers, *servers])
        db_session.flush()
        # The first of each pair is shared with the group. The second is not.
        db_session.add_all(
            [
                LLMProvider__UserGroup(
                    llm_provider_id=providers[0].id, user_group_id=group.id
                ),
                MCPServer__UserGroup(
                    mcp_server_id=servers[0].id, user_group_id=group.id
                ),
                Skill__UserGroup(skill_id=skills[0].id, user_group_id=group.id),
            ]
        )
        db_session.flush()

        remove_custom_user_groups__no_commit(db_session)

        for row in (*providers, *servers, *skills):
            db_session.refresh(row)
        assert providers[0].is_public
        assert servers[0].is_public
        assert skills[0].public_permission == SkillSharePermission.VIEWER
        assert not providers[1].is_public
        assert not servers[1].is_public
        assert skills[1].public_permission is None
    finally:
        db_session.rollback()
