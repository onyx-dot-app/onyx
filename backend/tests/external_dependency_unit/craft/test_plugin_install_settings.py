"""The install setting, choice, version and name order of each user
(``load_user_plugin_states``, ``order_skill_names``), read for many users and
plugins at one time.

Group settings and company settings are written directly, because no route
writes NOT_AVAILABLE or group settings yet (G3). Each test rolls its
transaction back."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.enums import PluginInstallationPolicy, SkillSharePermission
from onyx.db.models import (
    Marketplace,
    Plugin,
    PluginSkill,
    PluginVersion,
    Skill,
    User,
    UserGroup,
    UserPluginPreference,
)
from onyx.db.plugin import (
    get_or_create_organization_library__no_commit,
    set_plugin_preferences__no_commit,
)
from onyx.db.plugin_access import (
    NameHiddenReason,
    UserPluginState,
    load_user_plugin_states,
    order_skill_names,
)
from onyx.db.skill import list_runtime_skills_for_user, set_skill_public_permission
from onyx.file_store.file_store import FileStore
from onyx.skills import push
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_group,
    make_skill,
    make_user,
    set_current_version_validity,
    set_plugin_created_at,
    share_plugin_with_group,
    share_plugin_with_user,
)

REQUIRED = PluginInstallationPolicy.REQUIRED
DEFAULT = PluginInstallationPolicy.DEFAULT
AVAILABLE = PluginInstallationPolicy.AVAILABLE
NOT_AVAILABLE = PluginInstallationPolicy.NOT_AVAILABLE


def _set_company_setting(
    db_session: Session, skill: Skill, policy: PluginInstallationPolicy | None
) -> None:
    db_session.execute(
        update(Plugin).where(Plugin.id == skill.id).values(installation_policy=policy)
    )
    db_session.flush()


def _member_of(db_session: Session, *groups: UserGroup) -> User:
    user = make_user(db_session, standard_account=True)
    for group in groups:
        add_user_to_group(db_session, user, group)
    return user


def _states(
    db_session: Session, users: list[User], skills: list[Skill]
) -> dict[tuple[UUID, UUID], UserPluginState]:
    db_session.expire_all()
    return {
        (state.user_id, state.plugin_id): state
        for state in load_user_plugin_states(
            [user.id for user in users],
            db_session,
            plugin_ids=[skill.id for skill in skills],
        )
    }


def _setting(state: UserPluginState) -> PluginInstallationPolicy | None:
    """The setting the user gets, or None when the user cannot see it."""
    return state.installation_policy if state.visible else None


@pytest.fixture
def organization_library(db_session: Session) -> Iterator[Marketplace]:
    library = db_session.get(
        Marketplace, get_or_create_organization_library__no_commit(db_session)
    )
    assert library is not None
    original = library.default_installation_policy
    try:
        yield library
    finally:
        library.default_installation_policy = original
        db_session.flush()


def test_truth_table_for_many_users_and_plugins_in_one_query(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """Company REQUIRED, group A NOT_AVAILABLE. Group B has no setting on
    the first plugin and AVAILABLE on the second. Default groups (Basic) do
    not count, so a user in no other group gets the company setting."""
    owner = make_user(db_session, standard_account=True)
    group_a = make_group(db_session)
    group_b = make_group(db_session)
    b_no_setting = make_skill(db_session, author_user_id=owner.id, is_public=True)
    b_available = make_skill(db_session, author_user_id=owner.id, is_public=True)
    for skill, b_setting in ((b_no_setting, None), (b_available, AVAILABLE)):
        _set_company_setting(db_session, skill, REQUIRED)
        share_plugin_with_group(db_session, skill.id, group_a.id, None, NOT_AVAILABLE)
        share_plugin_with_group(db_session, skill.id, group_b.id, None, b_setting)
    a_only = _member_of(db_session, group_a)
    b_only = _member_of(db_session, group_b)
    both = _member_of(db_session, group_a, group_b)
    no_group = _member_of(db_session)

    states = _states(
        db_session, [a_only, b_only, both, no_group], [b_no_setting, b_available]
    )

    assert len(states) == 8
    expected = {
        (a_only, b_no_setting): None,
        (b_only, b_no_setting): REQUIRED,
        (both, b_no_setting): REQUIRED,
        (no_group, b_no_setting): REQUIRED,
        (a_only, b_available): None,
        (b_only, b_available): AVAILABLE,
        (both, b_available): AVAILABLE,
        (no_group, b_available): REQUIRED,
    }
    for (user, skill), setting in expected.items():
        state = states[(user.id, skill.id)]
        assert _setting(state) == setting, (user.email, skill.name)
        assert state.enabled == (setting == REQUIRED)


def test_a_plugin_with_no_setting_takes_its_marketplace_default(
    db_session: Session,
    organization_library: Marketplace,
    test_user: User,  # noqa: ARG001
) -> None:
    owner = make_user(db_session, standard_account=True)
    member = make_user(db_session, standard_account=True)
    no_setting = make_skill(db_session, author_user_id=owner.id, is_public=True)
    own_setting = make_skill(db_session, author_user_id=owner.id, is_public=True)
    _set_company_setting(db_session, no_setting, None)
    _set_company_setting(db_session, own_setting, AVAILABLE)

    for default in (DEFAULT, AVAILABLE, NOT_AVAILABLE):
        organization_library.default_installation_policy = default
        db_session.flush()
        states = _states(db_session, [member], [no_setting, own_setting])
        follows = states[(member.id, no_setting.id)]
        assert _setting(follows) == (None if default == NOT_AVAILABLE else default)
        assert follows.enabled == (default == DEFAULT)
        assert _setting(states[(member.id, own_setting.id)]) == AVAILABLE


def test_direct_share_gives_available_also_past_a_group_not_available(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """H7: a direct share gives at least AVAILABLE, with any company setting
    and past a group NOT_AVAILABLE. A group share whose own setting is
    NOT_AVAILABLE gives no access. A group row with no permission gives no
    access and does not make the group's members share recipients."""
    owner = make_user(db_session, standard_account=True)
    group_a = make_group(db_session)
    published = make_skill(db_session, author_user_id=owner.id, is_public=True)
    _set_company_setting(db_session, published, REQUIRED)
    share_plugin_with_group(db_session, published.id, group_a.id, None, NOT_AVAILABLE)
    hidden_company = make_skill(db_session, author_user_id=owner.id, is_public=True)
    _set_company_setting(db_session, hidden_company, NOT_AVAILABLE)

    direct_in_a = _member_of(db_session, group_a)
    direct_only = _member_of(db_session)
    a_only = _member_of(db_session, group_a)
    for skill in (published, hidden_company):
        share_plugin_with_user(
            db_session, skill.id, direct_in_a.id, SkillSharePermission.VIEWER
        )
        share_plugin_with_user(
            db_session, skill.id, direct_only.id, SkillSharePermission.VIEWER
        )

    states = _states(
        db_session,
        [direct_in_a, direct_only, a_only, owner],
        [published, hidden_company],
    )
    assert _setting(states[(direct_in_a.id, published.id)]) == AVAILABLE
    assert _setting(states[(a_only.id, published.id)]) is None
    assert _setting(states[(direct_only.id, published.id)]) == REQUIRED
    assert _setting(states[(direct_in_a.id, hidden_company.id)]) == AVAILABLE
    assert _setting(states[(direct_only.id, hidden_company.id)]) == AVAILABLE
    assert _setting(states[(a_only.id, hidden_company.id)]) is None
    # The owner still sees the plugin and can turn it on.
    assert _setting(states[(owner.id, hidden_company.id)]) == AVAILABLE
    assert states[(direct_in_a.id, published.id)].shared

    # A group share with its own setting NOT_AVAILABLE gives no access.
    private = make_skill(db_session, author_user_id=owner.id)
    group_g = make_group(db_session)
    member_g = _member_of(db_session, group_g)
    share_plugin_with_group(
        db_session,
        private.id,
        group_g.id,
        SkillSharePermission.VIEWER,
        NOT_AVAILABLE,
    )
    state = _states(db_session, [member_g], [private])[(member_g.id, private.id)]
    assert not state.visible and not state.shared and not state.enabled
    share_plugin_with_group(
        db_session, private.id, group_g.id, SkillSharePermission.VIEWER, None
    )
    state = _states(db_session, [member_g], [private])[(member_g.id, private.id)]
    assert state.visible and state.shared

    # A group row with no permission holds only a setting.
    share_plugin_with_group(db_session, private.id, group_g.id, None, REQUIRED)
    state = _states(db_session, [member_g], [private])[(member_g.id, private.id)]
    assert not state.visible and not state.shared and not state.enabled


def test_choices_under_each_setting(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """REQUIRED ignores an opt-out. DEFAULT is on until the user opts out.
    AVAILABLE is on only after an opt-in. NOT_AVAILABLE hides the plugin and
    ignores a saved choice, but keeps it."""
    owner = make_user(db_session, standard_account=True)
    user = make_user(db_session, standard_account=True)
    skills = {
        policy: make_skill(db_session, author_user_id=owner.id, is_public=True)
        for policy in (REQUIRED, DEFAULT, AVAILABLE, NOT_AVAILABLE)
    }
    for policy, skill in skills.items():
        _set_company_setting(db_session, skill, policy)

    def enabled() -> dict[PluginInstallationPolicy, bool]:
        states = _states(db_session, [user], list(skills.values()))
        return {
            policy: states[(user.id, skill.id)].enabled
            for policy, skill in skills.items()
        }

    assert enabled() == {
        REQUIRED: True,
        DEFAULT: True,
        AVAILABLE: False,
        NOT_AVAILABLE: False,
    }
    set_plugin_preferences__no_commit(
        user.id, [skills[REQUIRED].id, skills[DEFAULT].id], False, db_session
    )
    set_plugin_preferences__no_commit(
        user.id, [skills[AVAILABLE].id, skills[NOT_AVAILABLE].id], True, db_session
    )
    assert enabled() == {
        REQUIRED: True,
        DEFAULT: False,
        AVAILABLE: True,
        NOT_AVAILABLE: False,
    }
    saved = db_session.get(UserPluginPreference, (user.id, skills[NOT_AVAILABLE].id))
    assert saved is not None and saved.enabled
    # The saved choice counts again once the plugin is not hidden.
    _set_company_setting(db_session, skills[NOT_AVAILABLE], AVAILABLE)
    assert enabled()[NOT_AVAILABLE]


def _add_draft_version(db_session: Session, skill: Skill) -> UUID:
    """Version 2, which only moves current_version_id, as an edit of a
    published plugin does."""
    version_id = uuid4()
    db_session.add(
        PluginVersion(
            id=version_id,
            plugin_id=skill.id,
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
            frontmatter={"name": f"{skill.name}-draft", "description": "Draft"},
        )
    )
    db_session.execute(
        update(Plugin)
        .where(Plugin.id == skill.id)
        .values(current_version_id=version_id)
    )
    db_session.flush()
    return version_id


def test_version_each_kind_of_user_runs(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """The owner, editors and share recipients run the newest version. A user
    who gets the plugin only through the organization runs the published one,
    also when a group row with no permission gives a setting. A user with both
    runs the newest. Skill names come from the version each user runs."""
    owner = make_user(db_session, standard_account=True)
    editor = make_user(db_session, standard_account=True)
    viewer = make_user(db_session, standard_account=True)
    group = make_group(db_session)
    group_member = _member_of(db_session, group)
    setting_group = make_group(db_session)
    setting_member = _member_of(db_session, setting_group)
    org_only = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=owner.id)
    share_plugin_with_user(db_session, skill.id, editor.id, SkillSharePermission.EDITOR)
    share_plugin_with_user(db_session, skill.id, viewer.id, SkillSharePermission.VIEWER)
    share_plugin_with_group(
        db_session, skill.id, group.id, SkillSharePermission.VIEWER, None
    )
    share_plugin_with_group(db_session, skill.id, setting_group.id, None, DEFAULT)
    set_skill_public_permission(
        skill=skill,
        public_permission=SkillSharePermission.VIEWER,
        db_session=db_session,
    )
    plugin = db_session.get(Plugin, skill.id)
    assert plugin is not None and plugin.published_version_id is not None
    published_id = plugin.published_version_id
    draft_id = _add_draft_version(db_session, skill)
    users = [owner, editor, viewer, group_member, setting_member, org_only]

    states = _states(db_session, users, [skill])
    newest = {owner.id, editor.id, viewer.id, group_member.id}
    for user in users:
        state = states[(user.id, skill.id)]
        if user.id in newest:
            assert state.version_id == draft_id, user.email
            assert state.skill_names == (f"{skill.name}-draft",)
        else:
            assert state.version_id == published_id, user.email
            assert state.skill_names == (skill.name,)
    assert states[(setting_member.id, skill.id)].installation_policy == DEFAULT
    assert states[(setting_member.id, skill.id)].enabled

    # An empty published pointer means the newest version.
    db_session.execute(
        update(Plugin).where(Plugin.id == skill.id).values(published_version_id=None)
    )
    state = _states(db_session, [org_only], [skill])[(org_only.id, skill.id)]
    assert state.version_id == draft_id


def test_name_order(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """Required for the user, then published, then the user's own, then
    shared. The older plugin wins a tie. Hidden skills come back with a
    reason, and the runtime list keeps one skill for each name."""
    user = make_user(db_session, standard_account=True)
    owner = make_user(db_session, standard_account=True)
    name = f"name-order-{uuid4().hex[:8]}"
    required = make_skill(db_session, name=name, is_public=True)
    published = make_skill(db_session, name=name, is_public=True)
    own = make_skill(db_session, name=name, author_user_id=user.id)
    shared_old = make_skill(db_session, name=name, author_user_id=owner.id)
    shared_new = make_skill(db_session, name=name, author_user_id=owner.id)
    _set_company_setting(db_session, required, REQUIRED)
    _set_company_setting(db_session, published, DEFAULT)
    for age, skill in enumerate((shared_new, shared_old, own, published, required)):
        set_plugin_created_at(
            db_session, skill.id, datetime(2025, 1, 10 - age, tzinfo=UTC)
        )
    for skill in (shared_old, shared_new):
        share_plugin_with_user(
            db_session, skill.id, user.id, SkillSharePermission.VIEWER
        )
    set_plugin_preferences__no_commit(
        user.id, [own.id, shared_old.id, shared_new.id], True, db_session
    )
    all_skills = [required, published, own, shared_old, shared_new]

    def order() -> tuple[UUID | None, dict[UUID, NameHiddenReason]]:
        states = _states(db_session, [user], all_skills).values()
        result = order_skill_names(states)
        return result.kept.get(name), {
            entry.plugin_id: entry.reason for entry in result.hidden
        }

    def runtime_ids() -> set[UUID]:
        return {
            runtime.skill.id
            for runtime in list_runtime_skills_for_user(
                user=user, db_session=db_session
            )
            if runtime.name == name
        }

    for skill in all_skills:
        set_current_version_validity(db_session, skill.id, True)
    assert order() == (
        required.id,
        {
            published.id: NameHiddenReason.REQUIRED,
            own.id: NameHiddenReason.REQUIRED,
            shared_old.id: NameHiddenReason.REQUIRED,
            shared_new.id: NameHiddenReason.REQUIRED,
        },
    )
    assert runtime_ids() == {required.id}

    _set_company_setting(db_session, required, AVAILABLE)
    assert order() == (
        published.id,
        {
            own.id: NameHiddenReason.PUBLISHED,
            shared_old.id: NameHiddenReason.PUBLISHED,
            shared_new.id: NameHiddenReason.PUBLISHED,
        },
    )
    assert runtime_ids() == {published.id}

    set_plugin_preferences__no_commit(user.id, [published.id], False, db_session)
    assert order() == (
        own.id,
        {
            shared_old.id: NameHiddenReason.OWN,
            shared_new.id: NameHiddenReason.OWN,
        },
    )
    assert runtime_ids() == {own.id}

    set_plugin_preferences__no_commit(user.id, [own.id], False, db_session)
    assert order() == (shared_old.id, {shared_new.id: NameHiddenReason.OLDER})
    assert runtime_ids() == {shared_old.id}

    # A built-in name always wins.
    states = _states(db_session, [user], all_skills).values()
    result = order_skill_names(states, reserved_names={name})
    assert name not in result.kept
    assert {entry.reason for entry in result.hidden} == {NameHiddenReason.BUILT_IN}


def _bundle(name: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle_zip:
        bundle_zip.writestr("SKILL.md", f"---\nname: {name}\ndescription: d\n---\n")
    return output.getvalue()


def test_two_skills_with_one_name_do_not_stop_the_push(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session, standard_account=True)
    owner = make_user(db_session, standard_account=True)
    name = f"push-name-{uuid4().hex[:8]}"
    published = make_skill(db_session, name=name, is_public=True)
    shared = make_skill(db_session, name=name, author_user_id=owner.id)
    share_plugin_with_user(db_session, shared.id, user.id, SkillSharePermission.VIEWER)
    set_plugin_preferences__no_commit(
        user.id, [published.id, shared.id], True, db_session
    )
    for skill in (published, shared):
        set_current_version_validity(db_session, skill.id, True)
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.side_effect = lambda *_args, **_kwargs: io.BytesIO(
        _bundle(name)
    )
    monkeypatch.setattr(push, "get_default_file_store", lambda: file_store)
    monkeypatch.setattr(push, "persist_skill_validity", MagicMock())

    _apps, files = push.build_user_skills_payload(user, db_session)

    assert f"{name}/SKILL.md" in files
    read_ids = {call.args[0] for call in file_store.read_file.call_args_list}
    assert published.bundle_file_id in read_ids
    assert shared.bundle_file_id not in read_ids
