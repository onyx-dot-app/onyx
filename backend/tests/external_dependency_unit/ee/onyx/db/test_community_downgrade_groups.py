"""A downgrade to Community removes every custom user group without taking
access away: what a group shared becomes public and its members keep a group.
Each test rolls its transaction back."""

import logging
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.db.community_downgrade import (
    _UNCASCADED_GROUP_LINKS,
    remove_custom_user_groups__no_commit,
)
from onyx.configs.constants import TokenRateLimitPeriod, TokenRateLimitScope
from onyx.db.enums import (
    AccountType,
    GrantSource,
    IntegrationAuthMode,
    IntegrationKind,
    MarketplaceKind,
    Permission,
    PersonaSharePermission,
    PluginInstallationPolicy,
    SkillSharePermission,
    UserFileStatus,
)
from onyx.db.models import (
    Base,
    DocumentSet,
    DocumentSet__UserGroup,
    Integration,
    Integration__User,
    Integration__UserGroup,
    LLMProvider,
    LLMProvider__UserGroup,
    Marketplace,
    MCPServer,
    MCPServer__UserGroup,
    PermissionGrant,
    Persona,
    Persona__UserFile,
    Persona__UserGroup,
    Plugin,
    Plugin__User,
    Plugin__UserGroup,
    PluginSkill,
    TokenRateLimit,
    User,
    User__UserGroup,
    UserFile,
    UserGroup,
)
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.db.skill import replace_skill_shares, set_skill_public_permission
from onyx.db.users import (
    DEFAULT_ADMIN_GROUP_NAME,
    DEFAULT_BASIC_GROUP_NAME,
    assign_user_to_default_groups__no_commit,
    fetch_default_group,
)
from tests.external_dependency_unit.craft.db_helpers import make_skill
from tests.utils.plugin_access import ORGANIZATION_LIBRARY_ID


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
            token_budget=1,
            period=TokenRateLimitPeriod.DAILY,
            scope=TokenRateLimitScope.USER_GROUP,
            user_group_id=group_id,
        )
        db_session.add(rate_limit)
        db_session.flush()
        rate_limit_id = rate_limit.id
        recompute_user_permissions__no_commit(
            [basic_member.id, custom_only_member.id], db_session
        )
        db_session.refresh(basic_member)
        assert basic_member.is_group_manager

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


def _make_skill(db_session: Session, author: User, name: str | None = None) -> Plugin:
    return make_skill(
        db_session,
        name=name or f"downgrade-{uuid4().hex[:8]}",
        author_user_id=author.id,
    )


def _share_with_group(db_session: Session, skill: Plugin, group: UserGroup) -> None:
    replace_skill_shares(
        skill=skill,
        group_shares={group.id: SkillSharePermission.VIEWER},
        db_session=db_session,
    )


@pytest.mark.usefixtures("tenant_context")
def test_group_shared_skill_is_published_with_a_free_name_on_a_clash(
    db_session: Session,
) -> None:
    """The downgrade cannot stop, so a plugin whose name the Organization
    library has takes the next free name. The skill keeps its name."""
    try:
        owner = _make_user(db_session, in_basic=True)
        other = _make_user(db_session, in_basic=True)
        group = _make_group(db_session, [owner])
        skill_name = f"downgrade-{uuid4().hex[:8]}"
        published = _make_skill(db_session, other, name=skill_name)
        shared = _make_skill(db_session, owner, name=skill_name)
        set_skill_public_permission(
            skill=published,
            public_permission=SkillSharePermission.VIEWER,
            db_session=db_session,
        )
        _share_with_group(db_session, shared, group)

        remove_custom_user_groups__no_commit(db_session)

        db_session.refresh(shared)
        assert shared.marketplace_id == ORGANIZATION_LIBRARY_ID
        assert shared.name == f"{skill_name}-2"
        assert shared.published_version_id == shared.current_version_id
        assert (
            db_session.scalar(
                select(PluginSkill.frontmatter["name"].astext).where(
                    PluginSkill.plugin_version_id == shared.current_version_id
                )
            )
            == skill_name
        )
    finally:
        db_session.rollback()


def _group_shared_integration(
    db_session: Session, group: UserGroup, owner: User | None
) -> Integration:
    """A private MCP integration that is shared with the group."""
    server = MCPServer(
        owner=owner.email if owner is not None else "gone@example.com",
        name=f"downgrade-{uuid4().hex[:8]}",
        server_url="https://example.com/mcp",
        is_public=False,
    )
    db_session.add(server)
    db_session.flush()
    integration = Integration(
        kind=IntegrationKind.MCP,
        name="downgrade-mcp",
        auth_mode=IntegrationAuthMode.NONE,
        mcp_server_id=server.id,
        owner_user_id=owner.id if owner is not None else None,
    )
    db_session.add(integration)
    db_session.flush()
    db_session.add(
        Integration__UserGroup(
            integration_id=integration.id,
            user_group_id=group.id,
            permission=SkillSharePermission.VIEWER,
        )
    )
    db_session.flush()
    return integration


def _user_shares(db_session: Session, integration: Integration) -> set[UUID]:
    return set(
        db_session.scalars(
            select(Integration__User.user_id).where(
                Integration__User.integration_id == integration.id
            )
        )
    )


@pytest.mark.usefixtures("tenant_context")
@pytest.mark.parametrize("has_owner", [True, False])
@pytest.mark.parametrize(
    "company",
    [PluginInstallationPolicy.NOT_AVAILABLE, PluginInstallationPolicy.AVAILABLE],
)
def test_group_shared_integration_gives_its_members_a_share(
    db_session: Session, has_owner: bool, company: PluginInstallationPolicy
) -> None:
    """The members of a removed group keep the integration through a user
    share. The company setting does not change, so an integration that an
    admin closed stays closed and none opens to the organization."""
    try:
        owner = _make_user(db_session, in_basic=True)
        member = _make_user(db_session, in_basic=True)
        group = _make_group(db_session, [member])
        integration = _group_shared_integration(
            db_session, group, owner if has_owner else None
        )
        integration.installation_policy = company
        db_session.flush()

        remove_custom_user_groups__no_commit(db_session)

        db_session.refresh(integration)
        assert integration.installation_policy == company
        assert _user_shares(db_session, integration) == {member.id}
    finally:
        db_session.rollback()


@pytest.mark.usefixtures("tenant_context")
def test_a_group_setting_gives_its_members_a_share(db_session: Session) -> None:
    """A group row with no share but an Available setting gave its members
    access, so they keep it. A Not available setting gives none."""
    try:
        member = _make_user(db_session, in_basic=True)
        open_group = _make_group(db_session, [member])
        closed_member = _make_user(db_session, in_basic=True)
        closed_group = _make_group(db_session, [closed_member])
        integration = _group_shared_integration(db_session, open_group, None)
        db_session.query(Integration__UserGroup).filter_by(
            integration_id=integration.id
        ).update(
            {
                "permission": None,
                "installation_policy": PluginInstallationPolicy.AVAILABLE,
            }
        )
        db_session.add(
            Integration__UserGroup(
                integration_id=integration.id,
                user_group_id=closed_group.id,
                installation_policy=PluginInstallationPolicy.NOT_AVAILABLE,
            )
        )
        db_session.flush()

        remove_custom_user_groups__no_commit(db_session)

        assert _user_shares(db_session, integration) == {member.id}
    finally:
        db_session.rollback()


@pytest.mark.usefixtures("tenant_context")
def test_downgrade_publishes_from_plugin_group_grants_only(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    """The plugin group grants decide. A row with no permission (a group
    install setting only) or with NOT_AVAILABLE never publishes. The rows of
    the removed groups go with them, and the log names each published
    plugin."""
    try:
        owner = _make_user(db_session, in_basic=True)
        group = _make_group(db_session, [owner])
        shared = _make_skill(db_session, owner)
        setting_only = _make_skill(db_session, owner)
        not_available = _make_skill(db_session, owner)
        _share_with_group(db_session, shared, group)
        db_session.add_all(
            [
                Plugin__UserGroup(
                    plugin_id=setting_only.id,
                    user_group_id=group.id,
                    permission=None,
                    installation_policy=PluginInstallationPolicy.REQUIRED,
                ),
                Plugin__UserGroup(
                    plugin_id=not_available.id,
                    user_group_id=group.id,
                    permission=SkillSharePermission.VIEWER,
                    installation_policy=PluginInstallationPolicy.NOT_AVAILABLE,
                ),
            ]
        )
        db_session.flush()

        with caplog.at_level(logging.INFO):
            remove_custom_user_groups__no_commit(db_session)

        library_ids = set(
            db_session.scalars(
                select(Plugin.id).where(
                    Plugin.marketplace_id == ORGANIZATION_LIBRARY_ID,
                    Plugin.id.in_([shared.id, setting_only.id, not_available.id]),
                )
            )
        )
        assert library_ids == {shared.id}
        assert (
            db_session.scalar(
                select(Plugin__UserGroup.plugin_id).where(
                    Plugin__UserGroup.user_group_id == group.id
                )
            )
            is None
        )
        assert str(shared.id) in caplog.text
        assert str(setting_only.id) not in caplog.text
    finally:
        db_session.rollback()


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
            ]
        )
        db_session.flush()
        _share_with_group(db_session, skills[0], group)

        remove_custom_user_groups__no_commit(db_session)

        for row in (*providers, *servers, *skills):
            db_session.refresh(row)
        assert providers[0].is_public
        assert servers[0].is_public
        assert skills[0].marketplace_id == ORGANIZATION_LIBRARY_ID
        assert not providers[1].is_public
        assert not servers[1].is_public
        assert skills[1].marketplace_id != ORGANIZATION_LIBRARY_ID
    finally:
        db_session.rollback()


@pytest.mark.usefixtures("tenant_context")
def test_downgrade_shares_a_synced_plugin_with_group_members(
    db_session: Session,
) -> None:
    """A synced plugin cannot move to the Organization library, so the members
    of a removed group that shared it get a user share. A group with only an
    install setting gives no share."""
    try:
        member = _make_user(db_session, in_basic=True)
        outsider = _make_user(db_session, in_basic=True)
        group = _make_group(db_session, [member])
        setting_group = _make_group(db_session, [outsider])
        marketplace = Marketplace(
            kind=MarketplaceKind.GITHUB,
            name=f"downgrade-{uuid4().hex[:8]}",
            repository="acme/plugins",
            login_user_id=member.id,
        )
        db_session.add(marketplace)
        db_session.flush()
        synced = _make_skill(db_session, member)
        synced.marketplace_id = marketplace.id
        db_session.flush()
        _share_with_group(db_session, synced, group)
        db_session.add(
            Plugin__UserGroup(
                plugin_id=synced.id,
                user_group_id=setting_group.id,
                permission=None,
                installation_policy=PluginInstallationPolicy.NOT_AVAILABLE,
            )
        )
        db_session.flush()

        remove_custom_user_groups__no_commit(db_session)

        db_session.refresh(synced)
        assert synced.marketplace_id == marketplace.id
        assert db_session.scalars(
            select(Plugin__User.user_id).where(Plugin__User.plugin_id == synced.id)
        ).all() == [member.id]
    finally:
        db_session.rollback()
