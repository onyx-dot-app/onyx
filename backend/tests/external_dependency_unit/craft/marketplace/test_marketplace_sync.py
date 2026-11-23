import json
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.db.models import PluginVersion, User, UserIntegrationPreference
from onyx.db.skill import list_chat_skills, skill_user_states
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
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    make_mcp_integration,
)
from tests.unit.onyx.skills.marketplace_fixtures import CLAUDE, skill_md

_MCP_URL = "https://mcp.marketplace-sync.test/mcp"


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
    owner_row = db_session.get(User, owner.id)
    assert owner_row is not None
    # New plugins start off; the owner turns them on one at a time.
    assert not {
        skill.name for skill in list_chat_skills(db_session, owner_row, built_ins=False)
    } & {
        "alpha",
        "beta",
    }

    files = plugin_files("alpha", "beta")
    files["README.md"] = b"new readme\n"
    fake_github.push(OWNER, REPO, files)
    sync.sync_marketplace(marketplace.id)
    assert _versions(db_session, ids["alpha"]) == [1]

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
            "reason_code": None,
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


def test_sync_deletes_every_removed_entry(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    fake_github.push(
        OWNER, REPO, plugin_files(*[f"tool-{index}" for index in range(8)])
    )
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    sync.sync_marketplace(marketplace.id)

    fake_github.push(OWNER, REPO, plugin_files("tool-0", "new-tool"))
    result = sync.sync_marketplace(marketplace.id)
    assert result.status == MarketplaceSyncStatus.APPLIED
    assert len(result.deleted) == 7
    assert set(synced_plugins(db_session, marketplace.id)) == {"tool-0", "new-tool"}


def test_the_entry_name_names_the_plugin(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    files = plugin_files("alpha")
    files["plugins/alpha/.claude-plugin/plugin.json"] = json.dumps(
        {"name": "other-name"}
    ).encode()
    fake_github.push(OWNER, REPO, files)
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    sync.sync_marketplace(marketplace.id)
    plugin_id = synced_plugins(db_session, marketplace.id)["alpha"].id

    files["plugins/alpha/skills/alpha/SKILL.md"] += b"More steps.\n"
    fake_github.push(OWNER, REPO, files)
    result = sync.sync_marketplace(marketplace.id)
    assert result.versioned == [plugin_id]
    assert set(synced_plugins(db_session, marketplace.id)) == {"alpha"}


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

    assert sync.sync_marketplace(marketplace.id).status == MarketplaceSyncStatus.FAILED
    assert reload(db_session, marketplace).last_error == (
        f"GitHub did not find {OWNER}/{REPO}. If it is private, {owner.email} "
        "must connect GitHub, or another user must replace the login."
    )

    connections.connected.add(owner.id)
    result = sync.sync_marketplace(marketplace.id)
    assert result.status == MarketplaceSyncStatus.APPLIED
    assert result.blocked == ["missing"]
    assert set(synced_plugins(db_session, marketplace.id)) == {"remote"}
    assert reload(db_session, marketplace).last_error is None


def test_remote_entries_count_toward_the_marketplace_limits(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    fake_github.push("acme", "remote", {"skills/remote/SKILL.md": skill_md("remote")})
    files = plugin_files("alpha")
    files[CLAUDE] = catalog_with(
        [
            {"name": "alpha", "source": "./plugins/alpha"},
            {"name": "remote", "source": {"source": "github", "repo": "acme/remote"}},
        ]
    )
    fake_github.push(OWNER, REPO, files)
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )

    with patch("onyx.skills.marketplace.reader.GITHUB_SKILL_MAX_COUNT", 1):
        result = sync.sync_marketplace(marketplace.id)

    assert result.status == MarketplaceSyncStatus.FAILED
    assert reload(db_session, marketplace).last_error == (
        "The marketplace has more than 1 skills."
    )
    assert synced_plugins(db_session, marketplace.id) == {}


def test_external_repository_limit_depends_on_the_github_login(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    for repo in ("one", "two"):
        fake_github.push("acme", repo, {f"skills/{repo}/SKILL.md": skill_md(repo)})
    fake_github.push(
        OWNER,
        REPO,
        {
            CLAUDE: catalog_with(
                [
                    {
                        "name": repo,
                        "source": {"source": "github", "repo": f"acme/{repo}"},
                    }
                    for repo in ("one", "two")
                ]
            )
        },
    )
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )

    with (
        patch.object(sync, "REMOTE_REPOSITORY_MAX_COUNT", 1),
        patch.object(sync, "REMOTE_REPOSITORY_MAX_COUNT_WITH_LOGIN", 2),
    ):
        assert sync.sync_marketplace(marketplace.id).blocked == ["two"]
        assert reload(db_session, marketplace).last_sync_result == [
            {
                "key": "one",
                "path": "",
                "status": "ok",
                "reason": None,
                "reason_code": None,
            },
            {
                "key": "two",
                "path": None,
                "status": "blocked",
                "reason": "Connect GitHub to sync more than 1 external repositories.",
                "reason_code": "external_repository_limit_without_login",
            },
        ]

        connections.connected.add(owner.id)
        assert sync.sync_marketplace(marketplace.id).blocked == []
    assert set(synced_plugins(db_session, marketplace.id)) == {"one", "two"}


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


def test_personal_sync_leaves_new_plugins_and_integrations_off(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    integration, _ = make_mcp_integration(db_session, server_url=_MCP_URL)
    give_access(db_session, [integration])
    integration_id = integration.id
    db_session.execute(
        delete(UserIntegrationPreference).where(
            UserIntegrationPreference.user_id == owner.id
        )
    )
    db_session.commit()
    try:
        files = plugin_files("alpha")
        files["plugins/alpha/.mcp.json"] = json.dumps(
            {"mcpServers": {"main": {"type": "http", "url": _MCP_URL}}}
        ).encode()
        fake_github.push(OWNER, REPO, files)
        marketplace = make_marketplace(
            db_session, marketplace_ids, login=owner, owner=owner
        )

        result = sync.sync_marketplace(marketplace.id)

        assert result.status == MarketplaceSyncStatus.APPLIED
        db_session.expire_all()
        plugin = synced_plugins(db_session, marketplace.id)["alpha"]
        owner_row = db_session.get(User, owner.id)
        assert owner_row is not None
        assert not skill_user_states(owner_row, [plugin.id], db_session)[
            plugin.id
        ].enabled
        assert (
            db_session.scalar(
                select(UserIntegrationPreference.enabled).where(
                    UserIntegrationPreference.user_id == owner.id,
                    UserIntegrationPreference.integration_id == integration_id,
                )
            )
            is None
        )
    finally:
        delete_integrations(db_session, [integration_id])
