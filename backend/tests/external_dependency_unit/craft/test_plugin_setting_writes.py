"""Writes that keep names and install settings in a state the readers do not
have to repair (G3): plugin names, the hidden enabled row and every caller of
the install setting."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from onyx.db.enums import PluginInstallationPolicy, SkillSharePermission
from onyx.db.external_app import (
    delete_external_app__no_commit,
)
from onyx.db.models import (
    Plugin,
    Plugin__UserGroup,
    User,
    UserPluginPreference,
)
from onyx.db.plugin import (
    PluginAccessChange,
    PluginGroupSetting,
    _add_version_rows,
    add_plugin_version__no_commit,
    apply_plugin_access_change__no_commit,
    free_plugin_name,
    get_or_create_organization_library__no_commit,
    get_or_create_user_uploads__no_commit,
    lock_plugin,
    set_plugin_preferences__no_commit,
)
from onyx.db.plugin_access import load_user_plugin_states, order_skill_names
from onyx.db.skill import (
    delete_skill_for_user__no_commit,
    set_skill_enabled_for_user,
    skill_user_states,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.models import PluginSkillContent, PluginVersionContent
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_external_app,
    make_group,
    make_skill,
    make_user,
    share_plugin_with_group,
    share_plugin_with_user,
)


def _content(*skills: tuple[str, str]) -> PluginVersionContent:
    """A version with one plugin_skill row for each (path, name)."""
    return PluginVersionContent(
        bundle_file_id=f"bundle-{uuid4().hex[:8]}",
        bundle_sha256="0" * 64,
        is_valid=True,
        file_manifest=None,
        unpacked_size_bytes=None,
        file_count=None,
        skills=[
            PluginSkillContent(
                path=path,
                skill_md=None,
                frontmatter={"name": name, "description": "d"},
            )
            for path, name in skills
        ],
    )


def _create_plugin(
    db_session: Session,
    marketplace_id: UUID,
    name: str,
    author_id: UUID | None,
    content: PluginVersionContent,
) -> Plugin:
    """A plugin with version 1. A used name takes the next free name."""
    version_id = uuid4()
    plugin = Plugin(
        id=uuid4(),
        name=free_plugin_name(marketplace_id, name, db_session),
        description="",
        marketplace_id=marketplace_id,
        author_user_id=author_id,
        current_version_id=version_id,
        published_version_id=version_id if author_id is None else None,
    )
    db_session.add(plugin)
    db_session.flush()
    _add_version_rows(
        version_id=version_id,
        plugin_id=plugin.id,
        version_number=1,
        content=content,
        created_by=None,
        db_session=db_session,
    )
    return plugin


def _create(
    db_session: Session, marketplace_id: UUID, name: str, author_id: UUID | None
) -> Plugin:
    return _create_plugin(
        db_session, marketplace_id, name, author_id, _content(("", name))
    )


def test_one_name_in_two_marketplaces(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """plugin.name is unique per marketplace only."""
    name = f"deploy-{uuid4().hex[:8]}"
    first_author = make_user(db_session, standard_account=True)
    second_author = make_user(db_session, standard_account=True)
    plugins = [
        _create(
            db_session,
            get_or_create_user_uploads__no_commit(author.id, db_session),
            name,
            author.id,
        )
        for author in (first_author, second_author)
    ]
    plugins.append(
        _create(
            db_session,
            get_or_create_organization_library__no_commit(db_session),
            name,
            None,
        )
    )
    assert [plugin.name for plugin in plugins] == [name, name, name]
    # A second one in the same marketplace takes the next free name.
    assert (
        _create(
            db_session,
            get_or_create_user_uploads__no_commit(first_author.id, db_session),
            name,
            first_author.id,
        ).name
        == f"{name}-2"
    )


def test_a_version_with_a_new_skill_name(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """A plugin version can add a skill whose name another plugin uses. The
    write never compares a skill name with plugin.name; the name order keeps
    one of the two for the user."""
    user = make_user(db_session, standard_account=True)
    uploads_id = get_or_create_user_uploads__no_commit(user.id, db_session)
    taken = f"deploy-{uuid4().hex[:8]}"
    holder = _create(db_session, uploads_id, taken, user.id)
    plugin = _create_plugin(
        db_session,
        uploads_id,
        f"tools-{uuid4().hex[:8]}",
        user.id,
        _content(("alpha", f"alpha-{uuid4().hex[:8]}")),
    )
    plugin_name = plugin.name
    locked = lock_plugin(plugin.id, db_session)
    assert locked is not None
    added = add_plugin_version__no_commit(
        plugin=locked,
        content=_content(("alpha", f"alpha-{uuid4().hex[:8]}"), ("deploy", taken)),
        base_version_id=None,
        created_by=user,
        skip_if_unchanged=False,
        db_session=db_session,
    )
    assert added is not None
    assert locked.name == plugin_name
    set_plugin_preferences__no_commit(user.id, [holder.id, plugin.id], True, db_session)

    hidden = order_skill_names(load_user_plugin_states([user.id], db_session))
    assert len(hidden & {holder.id, plugin.id}) == 1


def test_toggle_and_auto_enable_read_the_group_setting(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """A group REQUIRED setting makes a skill required for its members, and a
    new same-name upload is not turned on over it. The toggle refusal is
    tested through the route (test_skill_setting_writes.py)."""
    member = make_user(db_session, standard_account=True)
    group = make_group(db_session)
    add_user_to_group(db_session, member, group)
    name = f"deploy-{uuid4().hex[:8]}"
    required = make_skill(db_session, name=name, is_public=True)
    share_plugin_with_group(
        db_session,
        required.id,
        group.id,
        None,
        PluginInstallationPolicy.REQUIRED,
    )

    state = skill_user_states(member, [required.id], db_session)[required.id]
    assert state.enabled and not state.can_toggle and state.required
    outsider = make_user(db_session, standard_account=True)
    assert not skill_user_states(outsider, [required.id], db_session)[
        required.id
    ].required
    upload = make_skill(db_session, name=name, author_user_id=member.id)
    with pytest.raises(OnyxError) as exc_info:
        set_skill_enabled_for_user(
            skill_id=upload.id, enabled=True, user=member, db_session=db_session
        )
    assert exc_info.value.error_code == OnyxErrorCode.SKILL_NAME_CONFLICT


def test_only_a_global_manager_deletes_a_group_required_skill(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """A group REQUIRED setting on a private skill counts for a member who can
    see the skill: through the group's share, or a share of their own. A
    setting-only row that reaches nobody does not block the owner."""
    group = make_group(db_session)
    member = make_user(db_session, standard_account=True)
    add_user_to_group(db_session, member, group)
    other_group = make_group(db_session)
    add_user_to_group(db_session, member, other_group)
    owner = make_user(db_session, standard_account=True)
    shared = make_skill(db_session, author_user_id=owner.id)
    share_plugin_with_group(
        db_session,
        shared.id,
        group.id,
        SkillSharePermission.VIEWER,
        PluginInstallationPolicy.REQUIRED,
    )
    setting_only = make_skill(db_session, author_user_id=owner.id)
    share_plugin_with_group(
        db_session, setting_only.id, group.id, None, PluginInstallationPolicy.REQUIRED
    )

    with pytest.raises(OnyxError) as exc_info:
        delete_skill_for_user__no_commit(shared, owner, db_session)
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    delete_skill_for_user__no_commit(setting_only, owner, db_session)

    by_user_share = make_skill(db_session, author_user_id=owner.id)
    share_plugin_with_user(
        db_session, by_user_share.id, member.id, SkillSharePermission.VIEWER
    )
    by_other_group = make_skill(db_session, author_user_id=owner.id)
    share_plugin_with_group(
        db_session, by_other_group.id, other_group.id, SkillSharePermission.VIEWER
    )
    for skill in (by_user_share, by_other_group):
        share_plugin_with_group(
            db_session, skill.id, group.id, None, PluginInstallationPolicy.REQUIRED
        )
        [state] = load_user_plugin_states([member.id], db_session, [skill.id])
        assert state.installation_policy == PluginInstallationPolicy.REQUIRED
        with pytest.raises(OnyxError) as exc_info:
            delete_skill_for_user__no_commit(skill, owner, db_session)
        assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS


def test_external_app_delete(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """The app has no link to the skill: a delete keeps the plugin's company
    setting, group settings and every choice."""
    user = make_user(db_session, standard_account=True)
    other = make_user(db_session, standard_account=True)
    group = make_group(db_session)
    skill = make_skill(db_session, is_public=True)
    app = make_external_app(
        db_session, skill=skill, auth_template={"Authorization": "Bearer {token}"}
    )
    db_session.execute(
        update(Plugin)
        .where(Plugin.id == skill.id)
        .values(installation_policy=PluginInstallationPolicy.REQUIRED)
    )
    share_plugin_with_group(
        db_session, skill.id, group.id, None, PluginInstallationPolicy.DEFAULT
    )
    set_plugin_preferences__no_commit(user.id, [skill.id], True, db_session)
    set_plugin_preferences__no_commit(other.id, [skill.id], False, db_session)

    delete_external_app__no_commit(db_session, app.id)
    db_session.expire_all()
    plugin = db_session.get(Plugin, skill.id)
    assert (
        plugin is not None
        and plugin.installation_policy == PluginInstallationPolicy.REQUIRED
    )
    group_setting = db_session.scalar(
        select(Plugin__UserGroup.installation_policy).where(
            Plugin__UserGroup.plugin_id == skill.id
        )
    )
    assert group_setting == PluginInstallationPolicy.DEFAULT
    assert db_session.get(UserPluginPreference, (user.id, skill.id)) is not None
    assert db_session.get(UserPluginPreference, (other.id, skill.id)) is not None


def test_two_same_name_skills_can_both_install_automatically(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """A company Default on one skill and a group Required on a second skill
    with the same name are allowed; the run-time name order picks one."""
    admin = make_user(db_session, is_admin=True)
    name = f"automatic-{uuid4().hex[:8]}"
    first = make_skill(db_session, name=name, is_public=True)
    second = make_skill(db_session, name=name, is_public=True)
    group = make_group(db_session)

    for change, skill in (
        (
            PluginAccessChange(
                company_installation_policy=PluginInstallationPolicy.DEFAULT
            ),
            first,
        ),
        (
            PluginAccessChange(
                group_settings=(
                    PluginGroupSetting(
                        group_id=group.id,
                        installation_policy=PluginInstallationPolicy.REQUIRED,
                    ),
                ),
            ),
            second,
        ),
    ):
        result = apply_plugin_access_change__no_commit(
            [skill.id], change, admin, db_session
        )
        assert result.failures == {}
