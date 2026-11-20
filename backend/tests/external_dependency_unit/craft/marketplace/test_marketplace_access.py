from typing import Any
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import PluginInstallationPolicy, SkillSharePermission
from onyx.db.marketplace import get_github_marketplace
from onyx.db.models import Plugin, PluginVersion, User
from onyx.db.plugin import (
    PluginAccessChange,
    PluginUserGrant,
    apply_plugin_access_change__no_commit,
    set_marketplace_default__no_commit,
)
from onyx.db.plugin_access import plugin_ids_visible_to
from onyx.db.skill import list_chat_skills
from onyx.db.users import delete_user_from_db
from onyx.skills.marketplace import sync
from tests.external_dependency_unit.craft.db_helpers import make_sandbox
from tests.external_dependency_unit.craft.fake_github import FakeGitHub
from tests.external_dependency_unit.craft.marketplace.helpers import (
    OWNER,
    REPO,
    Connections,
    existing_files,
    make_marketplace,
    plugin_files,
    synced_plugins,
)


def _on(db_session: Session, user: User) -> set[str]:
    db_session.expire_all()
    row = db_session.get(User, user.id)
    assert row is not None
    return {skill.name for skill in list_chat_skills(db_session, row, built_ins=False)}


def test_company_marketplace_follows_its_default(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    login, member, _ = users
    fake_github.push(OWNER, REPO, plugin_files("alpha", "beta"))
    marketplace = make_marketplace(
        db_session,
        marketplace_ids,
        login=login,
        owner=None,
        default=PluginInstallationPolicy.DEFAULT,
    )
    sync.sync_marketplace(marketplace.id)
    plugins = synced_plugins(db_session, marketplace.id)
    alpha_id, beta_id = plugins["alpha"].id, plugins["beta"].id
    assert all(plugin.author_user_id is None for plugin in plugins.values())
    assert all(
        plugin.published_version_id == plugin.current_version_id
        for plugin in plugins.values()
    )

    assert {"alpha", "beta"} <= _on(db_session, member)
    assert {"alpha", "beta"} <= _on(db_session, login)

    apply_plugin_access_change__no_commit(
        [beta_id],
        PluginAccessChange(
            company_installation_policy=PluginInstallationPolicy.DEFAULT
        ),
        None,
        db_session,
    ).raise_first_failure()
    db_session.commit()

    set_marketplace_default__no_commit(
        marketplace.id, PluginInstallationPolicy.AVAILABLE, db_session
    )
    db_session.commit()
    assert "alpha" not in _on(db_session, member)
    assert "beta" in _on(db_session, member)
    assert {alpha_id, beta_id} <= plugin_ids_visible_to(member.id, db_session)

    set_marketplace_default__no_commit(
        marketplace.id, PluginInstallationPolicy.NOT_AVAILABLE, db_session
    )
    db_session.commit()
    visible = plugin_ids_visible_to(member.id, db_session)
    assert alpha_id not in visible
    assert beta_id in visible


def test_personal_marketplace_is_seen_by_its_owner_and_shares(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    owner, shared, other = users
    fake_github.push(OWNER, REPO, plugin_files("alpha"))
    marketplace = make_marketplace(
        db_session,
        marketplace_ids,
        login=owner,
        owner=owner,
        default=PluginInstallationPolicy.DEFAULT,
    )
    sync.sync_marketplace(marketplace.id)
    plugin_id = synced_plugins(db_session, marketplace.id)["alpha"].id
    assert "alpha" in _on(db_session, owner)
    assert plugin_id not in plugin_ids_visible_to(shared.id, db_session)

    apply_plugin_access_change__no_commit(
        [plugin_id],
        PluginAccessChange(
            user_grants=(
                PluginUserGrant(
                    user_id=shared.id, permission=SkillSharePermission.VIEWER
                ),
            )
        ),
        None,
        db_session,
    ).raise_first_failure()
    db_session.commit()
    assert plugin_id in plugin_ids_visible_to(shared.id, db_session)
    assert plugin_id not in plugin_ids_visible_to(other.id, db_session)


def test_user_delete_removes_their_personal_marketplace(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    owner, shared, _ = users
    fake_github.push(OWNER, REPO, plugin_files("alpha"))
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    sync.sync_marketplace(marketplace.id)
    plugin = synced_plugins(db_session, marketplace.id)["alpha"]
    apply_plugin_access_change__no_commit(
        [plugin.id],
        PluginAccessChange(
            user_grants=(
                PluginUserGrant(
                    user_id=shared.id, permission=SkillSharePermission.VIEWER
                ),
            )
        ),
        None,
        db_session,
    ).raise_first_failure()
    make_sandbox(db_session, shared)
    db_session.commit()
    bundle_ids = [
        file_id
        for file_id in db_session.scalars(
            select(PluginVersion.bundle_file_id).where(
                PluginVersion.plugin_id == plugin.id
            )
        )
        if file_id is not None
    ]
    assert bundle_ids
    assert existing_files(db_session, bundle_ids) == set(bundle_ids)
    row = db_session.get(User, owner.id)
    assert row is not None

    with patch("onyx.skills.push.push_skills_and_commit") as push:
        delete_user_from_db(row, db_session)

    db_session.expire_all()
    assert db_session.get(User, owner.id) is None
    assert get_github_marketplace(marketplace.id, db_session) is None
    assert db_session.get(Plugin, plugin.id) is None
    assert existing_files(db_session, bundle_ids) == set()
    assert [set(call.args[0]) for call in push.call_args_list] == [{shared.id}]
