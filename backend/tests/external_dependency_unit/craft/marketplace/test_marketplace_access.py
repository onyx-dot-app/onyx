from typing import Any

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import PluginInstallationPolicy, SkillSharePermission
from onyx.db.models import User
from onyx.db.plugin import (
    PluginAccessChange,
    PluginUserGrant,
    apply_plugin_access_change__no_commit,
    set_marketplace_default__no_commit,
)
from onyx.db.plugin_access import get_visible_plugin_ids
from onyx.db.skill import list_chat_skills
from onyx.db.users import delete_user_from_db__no_commit
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.marketplace import sync
from tests.external_dependency_unit.craft.fake_github import FakeGitHub
from tests.external_dependency_unit.craft.marketplace.helpers import (
    OWNER,
    REPO,
    Connections,
    make_marketplace,
    plugin_files,
    synced_plugins,
)


def _on(db_session: Session, user: User) -> set[str]:
    db_session.expire_all()
    row = db_session.get(User, user.id)
    assert row is not None
    return {skill.name for skill in list_chat_skills(db_session, row)}


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

    # Installed by default: on for each user.
    assert {"alpha", "beta"} <= _on(db_session, member)
    assert {"alpha", "beta"} <= _on(db_session, login)

    # A plugin with its own setting does not move with the default.
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
    assert {alpha_id, beta_id} <= get_visible_plugin_ids(member.id, db_session)

    set_marketplace_default__no_commit(
        marketplace.id, PluginInstallationPolicy.NOT_AVAILABLE, db_session
    )
    db_session.commit()
    visible = get_visible_plugin_ids(member.id, db_session)
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
    assert plugin_id not in get_visible_plugin_ids(shared.id, db_session)

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
    assert plugin_id in get_visible_plugin_ids(shared.id, db_session)
    assert plugin_id not in get_visible_plugin_ids(other.id, db_session)


def test_personal_marketplace_blocks_its_owners_delete(
    db_session: Session,
    users: tuple[User, User, User],
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    row = db_session.get(User, owner.id)
    assert row is not None
    with pytest.raises(OnyxError) as exc:
        delete_user_from_db__no_commit(row, db_session)
    db_session.rollback()
    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    assert exc.value.extra == {
        "private_plugins": [],
        "personal_marketplaces": [
            {"id": str(marketplace.id), "name": marketplace.name}
        ],
    }
