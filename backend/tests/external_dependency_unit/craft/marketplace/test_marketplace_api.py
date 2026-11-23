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
from onyx.db.models import Marketplace, User
from onyx.db.skill import SkillUserState, set_skill_enabled_for_user, skill_user_states
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
from tests.external_dependency_unit.craft.db_helpers import make_skill, make_user
from tests.external_dependency_unit.craft.fake_github import FakeGitHub
from tests.external_dependency_unit.craft.marketplace.helpers import (
    OWNER,
    REPO,
    Connections,
    existing_files,
    http_request,
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

    with patch.object(sync, "enqueue_marketplace_sync", run_now):
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
        http_request(),
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


def test_preview_reads_a_folder_url_and_a_schemeless_url(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
) -> None:
    files = {
        f"market/{path}": content for path, content in plugin_files("alpha").items()
    }
    fake_github.push(OWNER, REPO, files, ref="release/1.0")
    preview = api.preview_marketplace(
        MarketplaceSourceRequest(
            repository=f"https://github.com/{OWNER}/{REPO}/tree/release/1.0/market"
        ),
        _fresh(db_session, users[0]),
        db_session,
    )
    assert (preview.status, preview.ref, preview.folder) == (
        "complete",
        "release/1.0",
        "market",
    )

    fake_github.push(OWNER, REPO, plugin_files("alpha"))
    schemeless = api.preview_marketplace(
        MarketplaceSourceRequest(repository=f"github.com/{OWNER}/{REPO}.git"),
        _fresh(db_session, users[0]),
        db_session,
    )
    assert schemeless.status == "complete"

    with pytest.raises(OnyxError) as exc:
        api.preview_marketplace(
            MarketplaceSourceRequest(repository=f"{OWNER}/{REPO}", ref="gone"),
            _fresh(db_session, users[0]),
            db_session,
        )
    assert exc.value.detail == f"The branch or folder 'gone' is not in {OWNER}/{REPO}."

    fake_github.rate_limit_reset = 1_800_000_000
    with pytest.raises(OnyxError) as exc:
        api.preview_marketplace(
            MarketplaceSourceRequest(repository=f"{OWNER}/{REPO}"),
            _fresh(db_session, users[0]),
            db_session,
        )
    assert exc.value.error_code == OnyxErrorCode.RATE_LIMITED
    assert exc.value.detail == (
        "GitHub's API rate limit has been reached. It resets at 08:00 UTC. "
        "Connect GitHub to raise the limit."
    )
    assert exc.value.extra == {"reset_at": "2027-01-15T08:00:00+00:00"}


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
    preview = api.preview_marketplace(
        MarketplaceSourceRequest(repository=f"{OWNER}/{REPO}"),
        _fresh(db_session, owner),
        db_session,
    )
    assert (preview.added_personal, preview.added_company) == (True, False)
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
    detail = api.get_marketplace(
        http_request(), personal_id, _fresh(db_session, owner), db_session
    )
    assert detail.scope == MarketplaceScope.PERSONAL
    assert detail.name == "acme-tools"
    assert detail.repository == f"{OWNER}/{REPO}"
    assert [entry.key for entry in detail.entries] == ["alpha"]
    assert detail.entries[0].plugin_id is not None
    assert detail.login_user is not None and detail.login_user.id == owner.id

    with pytest.raises(OnyxError) as exc:
        api.get_marketplace(
            http_request(), personal_id, _fresh(db_session, other), db_session
        )
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND
    with pytest.raises(OnyxError) as exc:
        api.get_marketplace(
            http_request(), personal_id, _fresh(db_session, manager), db_session
        )
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND
    with pytest.raises(OnyxError) as exc:
        api.sync_marketplace_now(
            http_request(),
            company_id,
            BackgroundTasks(),
            _fresh(db_session, owner),
            db_session,
        )
    assert exc.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS

    owner_list = api.list_marketplaces(
        http_request(), _fresh(db_session, owner), db_session
    )
    assert [
        (item.id, item.can_manage, item.default_installation_policy)
        for item in owner_list.marketplaces
        # Other tests and seed data may share the database.
        if item.id in (personal_id, company_id)
    ] == [
        (personal_id, True, None),
        (company_id, False, PluginInstallationPolicy.DEFAULT),
    ]
    member_view = api.get_marketplace(
        http_request(), company_id, _fresh(db_session, other), db_session
    )
    assert not member_view.can_manage
    manager_list = api.list_marketplaces(
        http_request(), _fresh(db_session, manager), db_session
    )
    assert [
        (item.id, item.can_manage)
        for item in manager_list.marketplaces
        if item.id in (personal_id, company_id)
    ] == [(company_id, True)]

    # The company already gets this source, in any letter case.
    with pytest.raises(OnyxError) as exc:
        api.create_marketplace(
            http_request(),
            MarketplaceCreateRequest(
                repository=f"https://github.com/{OWNER.upper()}/{REPO.title()}.git",
                scope=MarketplaceScope.PERSONAL,
            ),
            BackgroundTasks(),
            _fresh(db_session, other),
            db_session,
        )
    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    assert exc.value.detail == "Your organization already gets this marketplace."
    db_session.rollback()

    with pytest.raises(OnyxError):
        api.set_marketplace_default_access(
            http_request(),
            personal_id,
            MarketplaceDefaultAccessRequest(
                installation_policy=PluginInstallationPolicy.DEFAULT
            ),
            _fresh(db_session, owner),
            db_session,
        )
    db_session.rollback()
    required = api.set_marketplace_default_access(
        http_request(),
        company_id,
        MarketplaceDefaultAccessRequest(
            installation_policy=PluginInstallationPolicy.REQUIRED
        ),
        _fresh(db_session, manager),
        db_session,
    )
    assert required.default_installation_policy == PluginInstallationPolicy.REQUIRED
    changed = api.set_marketplace_default_access(
        http_request(),
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
        http_request(),
        marketplace_id,
        BackgroundTasks(),
        _fresh(db_session, manager),
        db_session,
    )
    detail = api.get_marketplace(
        http_request(), marketplace_id, _fresh(db_session, manager), db_session
    )
    assert [plugin.name for plugin in detail.plugins] == ["tool-0"]
    assert set(synced_plugins(db_session, marketplace_id)) == {"tool-0"}

    connections.connected.add(manager.id)
    detail = api.replace_marketplace_login(
        http_request(),
        marketplace_id,
        BackgroundTasks(),
        _fresh(db_session, manager),
        db_session,
    )
    assert detail.login_user is not None and detail.login_user.id == manager.id
    assert detail.login_has_github
    assert (
        synced_plugins(db_session, marketplace_id)["tool-0"].id == plugin_ids["tool-0"]
    )

    api.delete_marketplace(
        http_request(), marketplace_id, _fresh(db_session, manager), db_session
    )
    assert synced_plugins(db_session, marketplace_id) == {}
    with pytest.raises(OnyxError) as exc:
        api.get_marketplace(
            http_request(), marketplace_id, _fresh(db_session, manager), db_session
        )
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
    api.delete_marketplace(
        http_request(), marketplace_id, _fresh(db_session, owner), db_session
    )
    assert existing_files(db_session, staged_file_ids) == set()


def test_replace_login_without_github_clears_a_gone_login(
    db_session: Session,
    users: tuple[User, User, User],
    manager: User,
    fake_github: FakeGitHub,
    enqueued: list[UUID],  # noqa: ARG001
) -> None:
    gone = users[2]
    fake_github.push(OWNER, REPO, plugin_files("alpha"))
    marketplace_id = _create(db_session, manager, MarketplaceScope.COMPANY)
    gone_row = _fresh(db_session, gone)
    gone_row.is_active = False
    row = db_session.get(Marketplace, marketplace_id)
    assert row is not None
    row.login_user_id = gone.id
    db_session.commit()
    api.sync_marketplace_now(
        http_request(),
        marketplace_id,
        BackgroundTasks(),
        _fresh(db_session, manager),
        db_session,
    )
    detail = api.get_marketplace(
        http_request(), marketplace_id, _fresh(db_session, manager), db_session
    )
    assert detail.last_error is not None

    api.replace_marketplace_login(
        http_request(),
        marketplace_id,
        BackgroundTasks(),
        _fresh(db_session, manager),
        db_session,
    )
    detail = api.get_marketplace(
        http_request(), marketplace_id, _fresh(db_session, manager), db_session
    )
    assert detail.login_user is not None and detail.login_user.id == manager.id
    assert not detail.login_has_github
    assert detail.last_error is None
    assert set(synced_plugins(db_session, marketplace_id)) == {"alpha"}


def test_required_default_wins_a_member_skill_name(
    db_session: Session,
    users: tuple[User, User, User],
    manager: User,
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    enqueued: list[UUID],  # noqa: ARG001
) -> None:
    member = users[1]
    own = make_skill(db_session, name="alpha", author_user_id=member.id)
    db_session.commit()
    set_skill_enabled_for_user(
        skill_id=own.id,
        enabled=True,
        user=_fresh(db_session, member),
        db_session=db_session,
    )
    db_session.commit()

    fake_github.push(OWNER, REPO, plugin_files("alpha"))
    company_id = _create(db_session, manager, MarketplaceScope.COMPANY)
    synced = synced_plugins(db_session, company_id)["alpha"]
    api.set_marketplace_default_access(
        http_request(),
        company_id,
        MarketplaceDefaultAccessRequest(
            installation_policy=PluginInstallationPolicy.REQUIRED
        ),
        _fresh(db_session, manager),
        db_session,
    )

    states = skill_user_states(
        _fresh(db_session, member), [synced.id, own.id], db_session
    )
    assert states[synced.id] == SkillUserState(
        enabled=True, can_toggle=False, required=True
    )
    assert states[own.id] == SkillUserState(
        enabled=False, can_toggle=True, name_held_by=("alpha",)
    )


def test_a_basic_token_cannot_manage_company_marketplaces(
    db_session: Session,
    manager: User,
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    enqueued: list[UUID],  # noqa: ARG001
) -> None:
    fake_github.push(OWNER, REPO, plugin_files("alpha"))
    basic = http_request([Permission.BASIC_ACCESS])
    with pytest.raises(OnyxError) as exc:
        api.create_marketplace(
            basic,
            MarketplaceCreateRequest(
                repository=f"{OWNER}/{REPO}", scope=MarketplaceScope.COMPANY
            ),
            BackgroundTasks(),
            _fresh(db_session, manager),
            db_session,
        )
    assert exc.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    db_session.rollback()

    company_id = _create(db_session, manager, MarketplaceScope.COMPANY)
    view = api.get_marketplace(
        basic, company_id, _fresh(db_session, manager), db_session
    )
    assert not view.can_manage
    with pytest.raises(OnyxError) as exc:
        api.delete_marketplace(
            basic, company_id, _fresh(db_session, manager), db_session
        )
    assert exc.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
