"""Access reads come from the plugin tables.

Each test rolls its transaction back."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from onyx.db.enums import (
    PluginInstallationPolicy,
    SkillInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.models import (
    Marketplace,
    Plugin,
    PluginSkill,
    PluginVersion,
    Skill,
    User,
    UserGroup,
)
from onyx.db.plugin import (
    ORGANIZATION_LIBRARY_ID,
    get_or_create_organization_library__no_commit,
)
from onyx.db.plugin_access import version_user_runs
from onyx.db.skill import (
    SkillManagementPolicy,
    fetch_skill,
    list_runtime_skills_for_user,
    set_skill_enabled_for_user,
    set_skill_installation_policy,
    set_skill_public_permission,
    skill_user_states,
)
from onyx.db.users import delete_user_from_db__no_commit
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.response_helpers import skill_response_for_user
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_built_in_skill_row,
    make_group,
    make_skill,
    make_user,
    share_plugin_with_group,
    share_skill_with_group,
    share_skill_with_user,
)


def _visible(skill: Skill, user: User, db_session: Session) -> bool:
    return (
        fetch_skill(
            skill.id,
            policy=SkillManagementPolicy.VIEW,
            user=user,
            db_session=db_session,
        )
        is not None
    )


def _editable(skill: Skill, user: User, db_session: Session) -> bool:
    return (
        fetch_skill(
            skill.id,
            policy=SkillManagementPolicy.EDIT,
            user=user,
            db_session=db_session,
        )
        is not None
    )


def _ids(
    skills: dict[str, Skill], keep: Iterable[UUID] | None = None
) -> dict[UUID, str]:
    names = {skill.id: key for key, skill in skills.items()}
    if keep is None:
        return names
    return {skill_id: names[skill_id] for skill_id in keep if skill_id in names}


def test_access_results_match_the_skill_rows_except_organization_edit(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """Owners, user and group shares, published skills, a skill with no
    author, a built-in skill, choices and install settings give the results
    the skill rows gave, with one change: the organization only views a skill
    that had organization-wide edit."""
    owner = make_user(db_session, standard_account=True)
    viewer = make_user(db_session, standard_account=True)
    editor = make_user(db_session, standard_account=True)
    group_viewer = make_user(db_session, standard_account=True)
    group_editor = make_user(db_session, standard_account=True)
    outsider = make_user(db_session, standard_account=True)
    viewers_group = make_group(db_session)
    editors_group = make_group(db_session)
    add_user_to_group(db_session, group_viewer, viewers_group)
    add_user_to_group(db_session, group_editor, editors_group)

    tag = uuid4().hex[:8]
    skills = {
        "private": make_skill(
            db_session, name=f"eq-private-{tag}", author_user_id=owner.id
        ),
        "unshared": make_skill(
            db_session, name=f"eq-unshared-{tag}", author_user_id=owner.id
        ),
        "published": make_skill(
            db_session, name=f"eq-published-{tag}", author_user_id=owner.id
        ),
        "no_author": make_skill(db_session, name=f"eq-no-author-{tag}", is_public=True),
        "org_editor": make_skill(
            db_session,
            name=f"eq-org-editor-{tag}",
            is_public=True,
            public_permission=SkillSharePermission.EDITOR,
            author_user_id=owner.id,
        ),
        "built_in": make_built_in_skill_row(
            db_session, built_in_skill_id=f"eq-built-in-{tag}"
        ),
    }
    share_skill_with_user(db_session, skills["private"], viewer)
    share_skill_with_user(
        db_session, skills["private"], editor, SkillSharePermission.EDITOR
    )
    share_skill_with_group(db_session, skills["private"], viewers_group)
    share_skill_with_group(
        db_session, skills["private"], editors_group, SkillSharePermission.EDITOR
    )
    set_skill_public_permission(
        skill=skills["published"],
        public_permission=SkillSharePermission.VIEWER,
        db_session=db_session,
    )
    set_skill_installation_policy(
        skills["published"], SkillInstallationPolicy.DEFAULT, db_session
    )
    set_skill_installation_policy(
        skills["no_author"], SkillInstallationPolicy.REQUIRED, db_session
    )
    # Choices: the viewer turns the private skill on, the outsider turns the
    # installed-by-default skill off.
    set_skill_enabled_for_user(
        skill_id=skills["private"].id, enabled=True, user=viewer, db_session=db_session
    )
    set_skill_enabled_for_user(
        skill_id=skills["published"].id,
        enabled=False,
        user=outsider,
        db_session=db_session,
    )

    users = {
        "owner": owner,
        "viewer": viewer,
        "editor": editor,
        "group_viewer": group_viewer,
        "group_editor": group_editor,
        "outsider": outsider,
    }
    everyone_sees = {"published", "no_author", "org_editor", "built_in"}
    expected_visible = {
        "owner": everyone_sees | {"private", "unshared"},
        "viewer": everyone_sees | {"private"},
        "editor": everyone_sees | {"private"},
        "group_viewer": everyone_sees | {"private"},
        "group_editor": everyone_sees | {"private"},
        "outsider": everyone_sees,
    }
    # Before plugins, org_editor was editable by every user here.
    expected_editable = {
        "owner": {"private", "unshared", "published", "org_editor"},
        "viewer": set(),
        "editor": {"private"},
        "group_viewer": set(),
        "group_editor": {"private"},
        "outsider": set(),
    }
    on_by_default = {"published", "no_author", "built_in"}
    expected_enabled = {
        "owner": on_by_default,
        "viewer": on_by_default | {"private"},
        "editor": on_by_default,
        "group_viewer": on_by_default,
        "group_editor": on_by_default,
        "outsider": {"no_author", "built_in"},
    }

    for key, user in users.items():
        visible = {
            name for name, skill in skills.items() if _visible(skill, user, db_session)
        }
        assert visible == expected_visible[key], key
        editable = {
            name for name, skill in skills.items() if _editable(skill, user, db_session)
        }
        assert editable == expected_editable[key], key
        states = skill_user_states(
            user, (skill.id for skill in skills.values()), db_session
        )
        enabled = {
            name for skill_id, name in _ids(skills).items() if states[skill_id].enabled
        }
        assert enabled == expected_enabled[key], key
        runtime = set(
            _ids(
                skills,
                (
                    skill.id
                    for skill in list_runtime_skills_for_user(
                        user=user, db_session=db_session
                    )
                ),
            ).values()
        )
        assert runtime == expected_enabled[key], key
        # A required skill cannot be turned off; the others can be toggled.
        assert not states[skills["no_author"].id].can_toggle
        assert states[skills["published"].id].can_toggle


def test_a_plugin_with_no_setting_follows_its_marketplace_default(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    owner = make_user(db_session, standard_account=True)
    member = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=owner.id, is_public=True)
    plugin = db_session.get(Plugin, skill.id)
    assert plugin is not None and plugin.installation_policy is None
    library_id = get_or_create_organization_library__no_commit(db_session)
    library = db_session.get(Marketplace, library_id)
    assert library is not None
    original_default = library.default_installation_policy

    def state() -> tuple[bool, bool]:
        db_session.expire_all()
        return (
            _visible(skill, member, db_session),
            skill_user_states(member, [skill.id], db_session)[skill.id].enabled,
        )

    try:
        assert state() == (True, False)
        library.default_installation_policy = PluginInstallationPolicy.DEFAULT
        db_session.flush()
        assert state() == (True, True)
        library.default_installation_policy = PluginInstallationPolicy.NOT_AVAILABLE
        db_session.flush()
        assert state() == (False, False)
        # The author still sees it.
        assert _visible(skill, owner, db_session)
        # A setting on the plugin wins over the default.
        set_skill_installation_policy(
            skill, SkillInstallationPolicy.DEFAULT, db_session
        )
        assert state() == (True, True)
    finally:
        library.default_installation_policy = original_default
        db_session.flush()


def test_group_settings_take_the_most_open_value_and_a_share_gives_available(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """The truth table of the install setting: company REQUIRED, group A
    NOT_AVAILABLE, group B no setting. A direct share gives AVAILABLE past a
    group NOT_AVAILABLE. Group settings are written directly, since no route
    writes them yet."""
    owner = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=owner.id, is_public=True)
    set_skill_installation_policy(skill, SkillInstallationPolicy.REQUIRED, db_session)
    group_a = make_group(db_session)
    group_b = make_group(db_session)
    share_plugin_with_group(
        db_session,
        skill.id,
        group_a.id,
        None,
        PluginInstallationPolicy.NOT_AVAILABLE,
    )
    share_plugin_with_group(db_session, skill.id, group_b.id, None, None)

    def member_of(*groups: UserGroup) -> User:
        user = make_user(db_session, standard_account=True)
        for group in groups:
            add_user_to_group(db_session, user, group)
        return user

    a_only = member_of(group_a)
    b_only = member_of(group_b)
    both = member_of(group_a, group_b)
    shared = member_of(group_a)
    share_skill_with_user(db_session, skill, shared)

    def result(user: User) -> tuple[bool, bool, bool]:
        state = skill_user_states(user, [skill.id], db_session)[skill.id]
        return _visible(skill, user, db_session), state.enabled, state.can_toggle

    # NOT_AVAILABLE: hidden.
    assert result(a_only) == (False, False, False)
    # REQUIRED: on and locked.
    assert result(b_only) == (True, True, False)
    assert result(both) == (True, True, False)
    # A direct share: AVAILABLE, so visible, off, and the user can turn it on.
    assert result(shared) == (True, False, True)
    set_skill_enabled_for_user(
        skill_id=skill.id, enabled=True, user=shared, db_session=db_session
    )
    assert result(shared) == (True, True, True)

    # Group B AVAILABLE: the most open of NOT_AVAILABLE and AVAILABLE.
    share_plugin_with_group(
        db_session, skill.id, group_b.id, None, PluginInstallationPolicy.AVAILABLE
    )
    assert result(both) == (True, False, True)
    # A group row with no permission grants nothing.
    unrelated = make_skill(db_session, author_user_id=owner.id)
    share_plugin_with_group(
        db_session, unrelated.id, group_b.id, None, PluginInstallationPolicy.REQUIRED
    )
    assert not _visible(unrelated, b_only, db_session)


def _add_draft_version(db_session: Session, skill: Skill) -> UUID:
    """Add version 2 with a new description and move only the current pointer,
    as an edit does once a published plugin keeps drafts (V6)."""
    plugin = db_session.get(Plugin, skill.id)
    assert plugin is not None
    version_id = uuid4()
    db_session.add(
        PluginVersion(
            id=version_id,
            plugin_id=plugin.id,
            version_number=2,
            bundle_file_id=skill.bundle_file_id,
            bundle_sha256=skill.bundle_sha256,
        )
    )
    db_session.flush()
    db_session.add(
        PluginSkill(
            plugin_version_id=version_id,
            path="",
            frontmatter={"name": skill.name, "description": "Draft"},
        )
    )
    db_session.execute(
        update(Plugin)
        .where(Plugin.id == plugin.id)
        .values(current_version_id=version_id)
    )
    db_session.flush()
    return version_id


def test_version_each_user_runs(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """The owner and share recipients run the newest version. A user who sees
    the plugin only through the organization runs the published version. A
    user with both runs the newest."""
    owner = make_user(db_session, standard_account=True)
    recipient = make_user(db_session, standard_account=True)
    org_only = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=owner.id)
    share_skill_with_user(db_session, skill, recipient)
    set_skill_public_permission(
        skill=skill,
        public_permission=SkillSharePermission.VIEWER,
        db_session=db_session,
    )
    published_id = db_session.scalar(
        select(Plugin.published_version_id).where(Plugin.id == skill.id)
    )
    assert published_id is not None
    draft_id = _add_draft_version(db_session, skill)

    expected = {
        owner.id: (draft_id, "Draft"),
        recipient.id: (draft_id, "Draft"),
        org_only.id: (published_id, "d"),
    }
    for user in (owner, recipient, org_only):
        runs = db_session.scalar(
            select(version_user_runs(Plugin, user.id)).where(Plugin.id == skill.id)
        )
        description = skill_response_for_user(skill, user, db_session).description
        assert (runs, description) == expected[user.id], user.email

    # An empty published pointer means the newest version.
    db_session.execute(
        update(Plugin).where(Plugin.id == skill.id).values(published_version_id=None)
    )
    assert (
        db_session.scalar(
            select(version_user_runs(Plugin, org_only.id)).where(Plugin.id == skill.id)
        )
        == draft_id
    )


def test_user_delete_guard_reads_my_uploads(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """The guard asks whether the user's "My uploads" holds a plugin. It does
    not read the skill row's columns."""
    owner = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=owner.id)
    # The skill row says published, but the plugin is still private.
    skill.public_permission = SkillSharePermission.VIEWER
    db_session.flush()

    with pytest.raises(OnyxError) as exc:
        delete_user_from_db__no_commit(owner, db_session)
    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    assert "Transfer or delete this user's private skills" in exc.value.detail

    # Once published, the plugin stays in the Organization library with no
    # author and does not block the delete.
    skill.public_permission = None
    db_session.flush()
    set_skill_public_permission(
        skill=skill,
        public_permission=SkillSharePermission.VIEWER,
        db_session=db_session,
    )
    delete_user_from_db__no_commit(owner, db_session)
    plugin = db_session.get(Plugin, skill.id)
    assert plugin is not None
    db_session.refresh(plugin)
    assert plugin.author_user_id is None
    assert plugin.marketplace_id == ORGANIZATION_LIBRARY_ID
