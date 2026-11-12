"""Writes that keep names and install settings in a state the readers do not
have to repair (G3): plugin names, the hidden enabled row and every caller of
the install setting."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from onyx.db.enums import PluginInstallationPolicy
from onyx.db.external_app import (
    delete_external_app,
    disconnect_external_app_for_user,
)
from onyx.db.models import (
    Plugin,
    Plugin__UserGroup,
    User,
    UserPluginPreference,
)
from onyx.db.plugin import (
    add_plugin_version__no_commit,
    create_plugin__no_commit,
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


def _create(
    db_session: Session, marketplace_id: UUID, name: str, author_id: UUID | None
) -> Plugin:
    return create_plugin__no_commit(
        plugin_id=uuid4(),
        name=name,
        marketplace_id=marketplace_id,
        author_user_id=author_id,
        installation_policy=None,
        publish=author_id is None,
        content=_content(("", name)),
        created_by=None,
        db_session=db_session,
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
    plugin = create_plugin__no_commit(
        plugin_id=uuid4(),
        name=f"tools-{uuid4().hex[:8]}",
        marketplace_id=uploads_id,
        author_user_id=user.id,
        installation_policy=None,
        publish=False,
        content=_content(("alpha", f"alpha-{uuid4().hex[:8]}")),
        created_by=None,
        db_session=db_session,
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

    order = order_skill_names(load_user_plugin_states([user.id], db_session))
    assert order.kept[taken] in {holder.id, plugin.id}
    assert order.hidden == {holder.id, plugin.id} - {order.kept[taken]}


def test_toggle_and_auto_enable_read_the_group_setting(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """A group REQUIRED setting makes a skill required for its members: the
    toggle refuses, and a new same-name upload is not turned on over it."""
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
    assert state.enabled and not state.can_toggle
    with pytest.raises(OnyxError):
        set_skill_enabled_for_user(
            skill_id=required.id, enabled=False, user=member, db_session=db_session
        )

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
    group = make_group(db_session)
    owner = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=owner.id)
    share_plugin_with_group(
        db_session, skill.id, group.id, None, PluginInstallationPolicy.REQUIRED
    )

    with pytest.raises(OnyxError) as exc_info:
        delete_skill_for_user__no_commit(skill, owner, db_session)
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    delete_skill_for_user__no_commit(
        skill, make_user(db_session, is_admin=True), db_session
    )


def test_external_app_delete_and_disconnect(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """Disconnect deletes the user's enabled choices and keeps opt-outs. Delete
    resets the company setting to the Organization library default, keeps the
    group settings and deletes every choice."""
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

    disconnect_external_app_for_user(
        db_session, external_app_id=app.id, user_id=user.id
    )
    assert db_session.get(UserPluginPreference, (user.id, skill.id)) is None
    assert db_session.get(UserPluginPreference, (other.id, skill.id)) is not None

    delete_external_app(db_session, app.id)
    db_session.expire_all()
    plugin = db_session.get(Plugin, skill.id)
    assert plugin is not None and plugin.installation_policy is None
    group_setting = db_session.scalar(
        select(Plugin__UserGroup.installation_policy).where(
            Plugin__UserGroup.plugin_id == skill.id
        )
    )
    assert group_setting == PluginInstallationPolicy.DEFAULT
    assert db_session.get(UserPluginPreference, (other.id, skill.id)) is None
