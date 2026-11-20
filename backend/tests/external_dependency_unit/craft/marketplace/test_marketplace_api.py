import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.db.enums import Permission, PluginInstallationPolicy
from onyx.db.marketplace import get_github_marketplace
from onyx.db.models import User
from onyx.db.users import delete_user_from_db__no_commit
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill import marketplace_api as api
from onyx.server.features.skill.marketplace_models import (
    MarketplaceCreateRequest,
    MarketplaceDefaultAccessRequest,
    MarketplaceScope,
    MarketplaceSourceRequest,
)
from onyx.skills.marketplace import sync
from onyx.skills.marketplace.models import MarketplaceEntryStatus
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.craft.fake_github import FakeGitHub
from tests.external_dependency_unit.craft.marketplace.helpers import (
    OWNER,
    REPO,
    Connections,
    existing_files,
    plugin_files,
    synced_plugins,
)
from tests.unit.onyx.skills.marketplace_fixtures import CLAUDE, skill_md


@pytest.fixture
def enqueued(marketplace_ids: list[UUID]) -> Iterator[list[UUID]]:
    ids: list[UUID] = []

    def run_now(marketplace_id: UUID, _tasks: BackgroundTasks) -> None:
        ids.append(marketplace_id)
        if marketplace_id not in marketplace_ids:
            marketplace_ids.append(marketplace_id)
        sync.run_marketplace_sync(marketplace_id)

    with patch.object(api, "enqueue_marketplace_sync", run_now):
        yield ids


@pytest.fixture
def manager(db_session: Session, created_user_ids: list[UUID]) -> User:
    user = make_user(db_session, is_admin=True)
    db_session.commit()
    created_user_ids.append(user.id)
    assert has_global_permission(user, Permission.MANAGE_PLUGINS)
    return user


def _fresh(db_session: Session, user: User) -> User:
    db_session.expire_all()
    row = db_session.get(User, user.id)
    assert row is not None
    return row


def _create(
    db_session: Session,
    user: User,
    scope: MarketplaceScope,
    **fields: Any,
) -> UUID:
    return api.create_marketplace(
        MarketplaceCreateRequest(repository=f"{OWNER}/{REPO}", scope=scope, **fields),
        BackgroundTasks(),
        _fresh(db_session, user),
        db_session,
    ).id


def test_preview_reads_without_writing(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
) -> None:
    files = plugin_files("alpha")
    files[CLAUDE] = json.dumps(
        {
            "name": "acme-tools",
            "plugins": [
                {"name": "alpha", "source": "./plugins/alpha"},
                {
                    "name": "linear",
                    "source": "./linear",
                    "mcpServers": {
                        "linear": {"type": "http", "url": "https://mcp.lin.example/mcp"}
                    },
                },
                {"name": "npm", "source": {"source": "npm", "package": "x"}},
            ],
        }
    ).encode()
    files["linear/skills/triage/SKILL.md"] = skill_md("triage")
    revision = fake_github.push(OWNER, REPO, files)
    preview = api.preview_marketplace(
        MarketplaceSourceRequest(repository=f"https://github.com/{OWNER}/{REPO}"),
        _fresh(db_session, users[0]),
        db_session,
    )
    assert preview.status == "complete"
    assert preview.revision == revision
    assert preview.name == "acme-tools"
    entries = {entry.key: entry for entry in preview.entries}
    assert entries["alpha"].status == MarketplaceEntryStatus.OK
    assert [skill.name for skill in entries["alpha"].skills] == ["alpha"]
    assert [need.name for need in entries["linear"].needs] == ["linear"]
    assert entries["npm"].status == MarketplaceEntryStatus.NOT_SUPPORTED

    fake_github.push(OWNER, REPO, {CLAUDE: b"[]"})
    failed = api.preview_marketplace(
        MarketplaceSourceRequest(repository=f"{OWNER}/{REPO}"),
        _fresh(db_session, users[0]),
        db_session,
    )
    assert failed.status == "failed"
    assert failed.reason is not None


def test_scope_and_owner_rules(
    db_session: Session,
    users: tuple[User, User, User],
    manager: User,
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    enqueued: list[UUID],
) -> None:
    owner, other, _ = users
    fake_github.push(OWNER, REPO, plugin_files("alpha"))

    with pytest.raises(OnyxError) as exc:
        _create(db_session, owner, MarketplaceScope.COMPANY)
    assert exc.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS

    personal_id = _create(db_session, owner, MarketplaceScope.PERSONAL)
    assert enqueued == [personal_id]
    with pytest.raises(OnyxError) as exc:
        _create(db_session, owner, MarketplaceScope.PERSONAL)
    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    db_session.rollback()

    company_id = _create(
        db_session,
        manager,
        MarketplaceScope.COMPANY,
        default_installation_policy=PluginInstallationPolicy.DEFAULT,
    )
    detail = api.get_marketplace(personal_id, _fresh(db_session, owner), db_session)
    assert detail.scope == MarketplaceScope.PERSONAL
    assert detail.name == "acme-tools"
    assert detail.repository == f"{OWNER}/{REPO}"
    assert [entry.key for entry in detail.entries] == ["alpha"]
    assert detail.entries[0].plugin_id is not None
    assert detail.login_user is not None and detail.login_user.id == owner.id

    with pytest.raises(OnyxError) as exc:
        api.get_marketplace(personal_id, _fresh(db_session, other), db_session)
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND
    with pytest.raises(OnyxError) as exc:
        api.get_marketplace(personal_id, _fresh(db_session, manager), db_session)
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND
    with pytest.raises(OnyxError) as exc:
        api.sync_marketplace_now(
            company_id, BackgroundTasks(), _fresh(db_session, owner), db_session
        )
    assert exc.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS

    owner_list = api.list_marketplaces(_fresh(db_session, owner), db_session)
    assert [item.id for item in owner_list.marketplaces] == [personal_id]
    manager_list = api.list_marketplaces(_fresh(db_session, manager), db_session)
    assert [item.id for item in manager_list.marketplaces] == [company_id]

    with pytest.raises(OnyxError):
        api.set_marketplace_default_access(
            personal_id,
            MarketplaceDefaultAccessRequest(
                installation_policy=PluginInstallationPolicy.DEFAULT
            ),
            _fresh(db_session, owner),
            db_session,
        )
    with pytest.raises(OnyxError):
        api.set_marketplace_default_access(
            company_id,
            MarketplaceDefaultAccessRequest(
                installation_policy=PluginInstallationPolicy.REQUIRED
            ),
            _fresh(db_session, manager),
            db_session,
        )
    db_session.rollback()
    changed = api.set_marketplace_default_access(
        company_id,
        MarketplaceDefaultAccessRequest(
            installation_policy=PluginInstallationPolicy.NOT_AVAILABLE
        ),
        _fresh(db_session, manager),
        db_session,
    )
    assert changed.default_installation_policy == PluginInstallationPolicy.NOT_AVAILABLE


def test_sync_replace_login_and_delete(
    db_session: Session,
    manager: User,
    fake_github: FakeGitHub,
    connections: Connections,
    enqueued: list[UUID],  # noqa: ARG001
) -> None:
    names = [f"tool-{index}" for index in range(7)]
    fake_github.push(OWNER, REPO, plugin_files(*names))
    marketplace_id = _create(db_session, manager, MarketplaceScope.COMPANY)
    plugin_ids = {
        key: plugin.id
        for key, plugin in synced_plugins(db_session, marketplace_id).items()
    }
    assert set(plugin_ids) == set(names)

    fake_github.push(OWNER, REPO, plugin_files("tool-0"))
    api.sync_marketplace_now(
        marketplace_id, BackgroundTasks(), _fresh(db_session, manager), db_session
    )
    detail = api.get_marketplace(
        marketplace_id, _fresh(db_session, manager), db_session
    )
    assert [plugin.name for plugin in detail.plugins] == ["tool-0"]
    assert set(synced_plugins(db_session, marketplace_id)) == {"tool-0"}

    with pytest.raises(OnyxError):
        api.replace_marketplace_login(
            marketplace_id, BackgroundTasks(), _fresh(db_session, manager), db_session
        )
    db_session.rollback()
    connections.connected.add(manager.id)
    detail = api.replace_marketplace_login(
        marketplace_id, BackgroundTasks(), _fresh(db_session, manager), db_session
    )
    assert detail.login_user is not None and detail.login_user.id == manager.id
    assert (
        synced_plugins(db_session, marketplace_id)["tool-0"].id == plugin_ids["tool-0"]
    )

    api.delete_marketplace(marketplace_id, _fresh(db_session, manager), db_session)
    assert synced_plugins(db_session, marketplace_id) == {}
    with pytest.raises(OnyxError) as exc:
        api.get_marketplace(marketplace_id, _fresh(db_session, manager), db_session)
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND


def test_delete_removes_bundle_files(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    enqueued: list[UUID],  # noqa: ARG001
    staged_file_ids: list[str],
) -> None:
    owner = users[0]
    fake_github.push(OWNER, REPO, plugin_files("alpha", "beta"))
    marketplace_id = _create(db_session, owner, MarketplaceScope.PERSONAL)
    assert len(existing_files(db_session, staged_file_ids)) == 2
    api.delete_marketplace(marketplace_id, _fresh(db_session, owner), db_session)
    assert existing_files(db_session, staged_file_ids) == set()


def test_manager_removes_personal_marketplace_to_delete_its_owner(
    db_session: Session,
    users: tuple[User, User, User],
    manager: User,
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    enqueued: list[UUID],  # noqa: ARG001
) -> None:
    owner, other, _ = users
    fake_github.push(OWNER, REPO, plugin_files("alpha"))
    personal_id = _create(db_session, owner, MarketplaceScope.PERSONAL)

    with pytest.raises(OnyxError) as exc:
        api.delete_marketplace(personal_id, _fresh(db_session, other), db_session)
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND
    db_session.rollback()

    api.delete_marketplace(personal_id, _fresh(db_session, manager), db_session)
    assert get_github_marketplace(personal_id, db_session) is None
    delete_user_from_db__no_commit(_fresh(db_session, owner), db_session)
    db_session.commit()
    assert db_session.get(User, owner.id) is None
