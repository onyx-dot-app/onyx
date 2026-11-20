import json
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request

from onyx.db.enums import Permission, PluginInstallationPolicy
from onyx.db.marketplace import (
    create_github_marketplace__no_commit,
)
from onyx.db.models import FileRecord, Marketplace, Plugin, User
from onyx.skills.marketplace.models import GitHubMarketplaceConfig
from tests.external_dependency_unit.craft.fake_github import (
    GOOD_TOKEN,
)
from tests.unit.onyx.skills.marketplace_fixtures import CLAUDE, skill_md

OWNER = "acme"
REPO = "tools"


def plugin_files(*names: str, body: str = "") -> dict[str, bytes]:
    files: dict[str, bytes] = {
        CLAUDE: json.dumps(
            {
                "name": "acme-tools",
                "plugins": [
                    {"name": name, "source": f"./plugins/{name}"} for name in names
                ],
            }
        ).encode()
    }
    for name in names:
        files[f"plugins/{name}/.claude-plugin/plugin.json"] = json.dumps(
            {"name": name, "description": f"The {name} plugin."}
        ).encode()
        files[f"plugins/{name}/skills/{name}/SKILL.md"] = skill_md(name) + body.encode()
    return files


def catalog_with(plugins: list[dict[str, JsonValue]]) -> bytes:
    return json.dumps({"name": "acme-tools", "plugins": plugins}).encode()


class Connections:
    def __init__(self) -> None:
        self.connected: set[UUID] = set()

    def authorization_for(self, user_id: UUID, _db_session: Session) -> str | None:
        return GOOD_TOKEN if user_id in self.connected else None


def existing_files(db_session: Session, file_ids: list[str]) -> set[str]:
    db_session.expire_all()
    return set(
        db_session.scalars(
            select(FileRecord.file_id).where(FileRecord.file_id.in_(file_ids))
        )
    )


def make_marketplace(
    db_session: Session,
    marketplace_ids: list[UUID],
    *,
    login: User,
    owner: User | None,
    default: PluginInstallationPolicy = PluginInstallationPolicy.AVAILABLE,
    folder: str | None = None,
    ref: str | None = None,
) -> Marketplace:
    marketplace = create_github_marketplace__no_commit(
        name=f"{OWNER}/{REPO}",
        config=GitHubMarketplaceConfig(owner=OWNER, repo=REPO, folder=folder, ref=ref),
        owner_user_id=owner.id if owner is not None else None,
        login_user_id=login.id,
        default_installation_policy=default,
        db_session=db_session,
    )
    db_session.commit()
    marketplace_ids.append(marketplace.id)
    return marketplace


def synced_plugins(db_session: Session, marketplace_id: UUID) -> dict[str, Plugin]:
    db_session.expire_all()
    return {
        plugin.name: plugin
        for plugin in db_session.scalars(
            select(Plugin).where(Plugin.marketplace_id == marketplace_id)
        )
    }


def reload(db_session: Session, marketplace: Marketplace) -> Marketplace:
    db_session.expire_all()
    fresh = db_session.get(Marketplace, marketplace.id)
    if fresh is None:
        raise AssertionError("marketplace is gone")
    return fresh


def http_request(token_scopes: list[Permission] | None = None) -> Request:
    """A route request; ``token_scopes`` caps a token as the auth layer does."""
    request = Request({"type": "http"})
    if token_scopes is not None:
        request.state.token_scopes = token_scopes
    return request
