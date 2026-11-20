import json
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db import marketplace as marketplace_db
from onyx.db.marketplace import confirm_marketplace_deletes__no_commit
from onyx.db.models import PluginVersion, User
from onyx.db.skill import list_chat_skills
from onyx.skills.marketplace import sync
from onyx.skills.marketplace.models import (
    MarketplaceSyncResult,
    MarketplaceSyncStatus,
)
from tests.external_dependency_unit.craft.fake_github import FakeGitHub
from tests.external_dependency_unit.craft.marketplace.helpers import (
    OWNER,
    REPO,
    Connections,
    catalog_with,
    existing_files,
    make_marketplace,
    plugin_files,
    reload,
    synced_plugins,
)
from tests.unit.onyx.skills.marketplace_fixtures import CLAUDE, skill_md


def _versions(db_session: Session, plugin_id: Any) -> list[int]:
    return list(
        db_session.scalars(
            select(PluginVersion.version_number)
            .where(PluginVersion.plugin_id == plugin_id)
            .order_by(PluginVersion.version_number)
        )
    )


def test_personal_sync_creates_versions_and_deletes(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    fake_github.push(OWNER, REPO, plugin_files("alpha", "beta"))
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )

    result = sync.sync_marketplace(marketplace.id)
    assert result.status == MarketplaceSyncStatus.APPLIED
    plugins = synced_plugins(db_session, marketplace.id)
    assert set(plugins) == {"alpha", "beta"}
    assert all(plugin.author_user_id == owner.id for plugin in plugins.values())
    assert all(plugin.published_version_id is None for plugin in plugins.values())
    ids = {key: plugin.id for key, plugin in plugins.items()}
    stored = reload(db_session, marketplace)
    assert stored.name == "acme-tools"
    assert stored.last_error is None
    assert stored.last_synced_revision is not None
    assert [item["status"] for item in stored.last_sync_result or []] == ["ok", "ok"]
    # A new personal plugin is on for its owner.
    owner_row = db_session.get(User, owner.id)
    assert owner_row is not None
    assert {skill.name for skill in list_chat_skills(db_session, owner_row)} >= {
        "alpha",
        "beta",
    }

    # A commit that changes nothing in the plugins adds no version.
    files = plugin_files("alpha", "beta")
    files["README.md"] = b"new readme\n"
    fake_github.push(OWNER, REPO, files)
    sync.sync_marketplace(marketplace.id)
    assert _versions(db_session, ids["alpha"]) == [1]

    # A changed file adds a version; a removed entry deletes its plugin.
    fake_github.push(OWNER, REPO, plugin_files("alpha", body="More steps.\n"))
    result = sync.sync_marketplace(marketplace.id)
    assert result.deleted == [ids["beta"]]
    assert result.versioned == [ids["alpha"]]
    after = synced_plugins(db_session, marketplace.id)
    assert set(after) == {"alpha"}
    assert _versions(db_session, ids["alpha"]) == [1, 2]
    version = db_session.get(PluginVersion, after["alpha"].current_version_id)
    assert version is not None
    assert version.created_by_user_id == owner.id
    assert version.source_tree_sha is not None


def test_blocked_entry_keeps_its_plugin(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    fake_github.push(OWNER, REPO, plugin_files("alpha"))
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    sync.sync_marketplace(marketplace.id)
    plugin = synced_plugins(db_session, marketplace.id)["alpha"]
    version_id = plugin.current_version_id

    files = plugin_files("alpha")
    files["plugins/alpha/skills/alpha/SKILL.md"] = b"no frontmatter"
    fake_github.push(OWNER, REPO, files)
    result = sync.sync_marketplace(marketplace.id)
    assert result.status == MarketplaceSyncStatus.APPLIED
    assert result.blocked == ["alpha"]
    kept = synced_plugins(db_session, marketplace.id)["alpha"]
    assert kept.current_version_id == version_id
    assert reload(db_session, marketplace).last_sync_result == [
        {
            "key": "alpha",
            "path": "plugins/alpha",
            "status": "blocked",
            "reason": result_reason(reload(db_session, marketplace).last_sync_result),
        }
    ]


def result_reason(results: list[dict[str, Any]] | None) -> str:
    assert results
    reason = results[0]["reason"]
    assert isinstance(reason, str) and "SKILL.md" in reason
    return reason


def test_failed_read_changes_nothing(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    fake_github.push(OWNER, REPO, plugin_files("alpha"))
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    sync.sync_marketplace(marketplace.id)
    revision = reload(db_session, marketplace).last_synced_revision

    fake_github.push(OWNER, REPO, {CLAUDE: b"{broken"})
    result = sync.sync_marketplace(marketplace.id)
    assert result.status == MarketplaceSyncStatus.FAILED
    stored = reload(db_session, marketplace)
    assert stored.last_error is not None and "not valid JSON" in stored.last_error
    assert stored.last_synced_revision == revision
    assert set(synced_plugins(db_session, marketplace.id)) == {"alpha"}


def test_delete_guard_waits_for_confirmation(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    names = [f"tool-{index}" for index in range(8)]
    fake_github.push(OWNER, REPO, plugin_files(*names))
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    sync.sync_marketplace(marketplace.id)

    revision = fake_github.push(OWNER, REPO, plugin_files("tool-0", "new-tool"))
    result = sync.sync_marketplace(marketplace.id)
    assert result.status == MarketplaceSyncStatus.NEEDS_CONFIRMATION
    stored = reload(db_session, marketplace)
    assert stored.pending_delete_revision == revision
    assert len(synced_plugins(db_session, marketplace.id)) == 8
    pending = marketplace_db.pending_delete_plugins(stored, db_session)
    assert sorted(plugin.entry_key for plugin in pending) == names[1:]

    confirm_marketplace_deletes__no_commit(marketplace.id, revision, db_session)
    db_session.commit()
    assert set(synced_plugins(db_session, marketplace.id)) == {"tool-0"}
    result = sync.sync_marketplace(marketplace.id)
    assert result.status == MarketplaceSyncStatus.APPLIED
    assert set(synced_plugins(db_session, marketplace.id)) == {"tool-0", "new-tool"}


def test_failed_upload_leaves_no_rows_and_no_files(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
    staged_file_ids: list[str],
) -> None:
    owner = users[0]
    fake_github.push(OWNER, REPO, plugin_files("alpha", "beta"))
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    real_store = sync.store_version_content
    calls = 0

    def fail_second(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("storage is down")
        return real_store(*args, **kwargs)

    with (
        patch.object(sync, "store_version_content", fail_second),
        pytest.raises(RuntimeError),
    ):
        sync.sync_marketplace(marketplace.id)
    assert synced_plugins(db_session, marketplace.id) == {}
    assert len(staged_file_ids) == 1
    assert existing_files(db_session, staged_file_ids) == set()

    # The next sync works.
    assert sync.sync_marketplace(marketplace.id).status == MarketplaceSyncStatus.APPLIED
    assert set(synced_plugins(db_session, marketplace.id)) == {"alpha", "beta"}


def test_failed_commit_leaves_no_rows_and_no_files(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
    staged_file_ids: list[str],
) -> None:
    owner = users[0]
    fake_github.push(OWNER, REPO, plugin_files("alpha", "beta"))
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    real_apply = sync.apply_marketplace_sync__no_commit

    def apply_then_fail(**kwargs: Any) -> MarketplaceSyncResult:
        real_apply(**kwargs)
        raise RuntimeError("commit failed")

    with (
        patch.object(sync, "apply_marketplace_sync__no_commit", apply_then_fail),
        pytest.raises(RuntimeError),
    ):
        sync.sync_marketplace(marketplace.id)
    assert synced_plugins(db_session, marketplace.id) == {}
    assert len(staged_file_ids) == 2
    assert existing_files(db_session, staged_file_ids) == set()
    assert reload(db_session, marketplace).last_synced_revision is None


def test_truncated_tree_adds_no_extra_version(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    fake_github.push(OWNER, REPO, plugin_files("alpha"))
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    sync.sync_marketplace(marketplace.id)
    plugin = synced_plugins(db_session, marketplace.id)["alpha"]

    fake_github.repositories[(OWNER, REPO)].truncated_tree = True
    fake_github.push(OWNER, REPO, plugin_files("alpha") | {"other.txt": b"x"})
    sync.sync_marketplace(marketplace.id)
    assert _versions(db_session, plugin.id) == [1]
    assert reload(db_session, marketplace).last_synced_tree_sha is None


def test_remote_entries_and_private_repository(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    fake_github.push(
        "acme",
        "remote",
        {"skills/remote/SKILL.md": skill_md("remote")},
    )
    fake_github.push(
        OWNER,
        REPO,
        {
            CLAUDE: catalog_with(
                [
                    {
                        "name": "remote",
                        "source": {"source": "github", "repo": "acme/remote"},
                    },
                    {
                        "name": "missing",
                        "source": {"source": "github", "repo": "acme/missing"},
                    },
                ]
            )
        },
        private=True,
    )
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )

    # A private repository and no GitHub connection.
    assert sync.sync_marketplace(marketplace.id).status == MarketplaceSyncStatus.FAILED
    assert reload(db_session, marketplace).last_error == (
        f"The GitHub connection of {owner.email} is gone. Replace the login."
    )

    connections.connected.add(owner.id)
    result = sync.sync_marketplace(marketplace.id)
    assert result.status == MarketplaceSyncStatus.APPLIED
    assert result.blocked == ["missing"]
    assert set(synced_plugins(db_session, marketplace.id)) == {"remote"}
    assert reload(db_session, marketplace).last_error is None


def test_login_user_gone(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    owner, login, _ = users
    fake_github.push(OWNER, REPO, plugin_files("alpha"))
    marketplace = make_marketplace(db_session, marketplace_ids, login=login, owner=None)
    login_row = db_session.get(User, login.id)
    assert login_row is not None
    login_row.is_active = False
    db_session.commit()
    assert sync.sync_marketplace(marketplace.id).status == MarketplaceSyncStatus.FAILED
    assert reload(db_session, marketplace).last_error == sync.LOGIN_GONE_ERROR
    assert owner.id != login.id


def test_entry_with_mcp_server_has_a_need(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    fake_github.push(
        OWNER,
        REPO,
        {
            CLAUDE: catalog_with(
                [
                    {
                        "name": "linear",
                        "source": "./linear",
                        "mcpServers": {
                            "linear": {
                                "type": "http",
                                "url": "https://mcp.linear.example/mcp",
                            }
                        },
                    }
                ]
            ),
            "linear/README.md": b"Linear\n",
        },
    )
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    sync.sync_marketplace(marketplace.id)
    plugin = synced_plugins(db_session, marketplace.id)["linear"]
    version = db_session.get(PluginVersion, plugin.current_version_id)
    assert version is not None
    assert [need["name"] for need in version.needs or []] == ["linear"]
    assert json.loads(json.dumps(version.manifest))["name"] == "linear"
