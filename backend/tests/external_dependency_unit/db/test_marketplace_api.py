"""Real request validation and PostgreSQL authority; controlled GitHub transport."""

from collections.abc import Generator
from unittest.mock import patch

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.models import FileRecord, Marketplace, User
from onyx.server.features.skill import marketplace_api as api
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.db.skill_api_client import (
    client_for as skill_client_for,
)
from tests.external_dependency_unit.db.test_marketplace_management import (
    connect,
    create,
)
from tests.external_dependency_unit.db.test_marketplace_sync import GitHub
from tests.external_dependency_unit.db.test_skill_access_actor import (
    Revocation,
    admin_with_basic,
    revoke,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import manager
from tests.unit.onyx.skills.marketplace_fixtures import CLAUDE, _archive, _catalog, _md

pytestmark = pytest.mark.usefixtures("tenant_context", "enable_ee")
SOURCE = {
    "provider": "github",
    "provider_config": {"owner": "acme", "repo": "tools", "ref": "main"},
}


def client_for(
    user: User, session: Session, scopes: list[Permission] | None = None
) -> TestClient:
    return skill_client_for(user, session, scopes, routers=(api.router,))


@pytest.fixture
def github() -> Generator[GitHub, None, None]:
    upstream = GitHub()
    with (
        patch("onyx.utils.github.ssrf_safe_get", upstream.get),
        patch(
            "onyx.skills.marketplace.provider.github_authorization_header",
            return_value="Bearer fixture",
        ),
    ):
        yield upstream


def test_preview_reads_one_commit_without_writes(
    db_session: Session, github: GitHub
) -> None:
    actor = make_user(db_session, standard_account=True)
    db_session.commit()
    github.archive = _archive(
        {
            CLAUDE: _catalog(skills=["./skills"]),
            "skills/hello/SKILL.md": _md(),
            "skills/broken/SKILL.md": b"no frontmatter",
        },
        kind="tar",
        wrapper="repo/",
    )
    before = (
        db_session.scalar(select(func.count()).select_from(Marketplace)),
        db_session.scalar(select(func.count()).select_from(FileRecord)),
    )
    db_session.rollback()
    get = github.get

    def without_lock(url: str, **kwargs: object) -> requests.Response:
        assert not db_session.in_transaction()
        return get(url, **kwargs)

    with (
        client_for(actor, db_session) as client,
        patch("onyx.utils.github.ssrf_safe_get", without_lock),
    ):
        response = client.post("/marketplaces/preview", json=SOURCE)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "complete" and data["revision"] == github.revision
    entries = {item["entry_key"]: item for item in data["entries"]}
    assert entries["tools/hello"] == {
        "status": "ok",
        "entry_key": "tools/hello",
        "path": "skills/hello",
        "name": "hello",
        "description": "A test skill",
    }
    assert entries["tools/broken"]["status"] == "blocked"
    assert len(github.urls) == 2
    assert github.urls[-1].endswith("/tar.gz/" + data["revision"])
    assert "bundle_bytes" not in response.text and "fixture" not in response.text
    assert before == (
        db_session.scalar(select(func.count()).select_from(Marketplace)),
        db_session.scalar(select(func.count()).select_from(FileRecord)),
    )


@pytest.mark.parametrize("unsupported", [False, True])
def test_preview_explains_missing_catalog_and_unsupported_plugins(
    db_session: Session,
    github: GitHub,
    unsupported: bool,
) -> None:
    actor = make_user(db_session, standard_account=True)
    db_session.commit()
    files = {"skills/hello/SKILL.md": _md()}
    if unsupported:
        files[CLAUDE] = _catalog(mcpServers={"service": {"command": "node"}})
    github.archive = _archive(files, kind="tar", wrapper="repo/")
    with client_for(actor, db_session) as client:
        response = client.post("/marketplaces/preview", json=SOURCE)
    assert response.status_code == 200, response.text
    data = response.json()
    if unsupported:
        assert data["status"] == "complete"
        assert data["entries"][0]["status"] == "not_supported"
    else:
        assert data["status"] == "failed" and data["reason"]
        assert "entries" not in data


@pytest.mark.parametrize("kind", ["ordinary", "scoped", "global"])
@pytest.mark.parametrize("personal", [False, True])
def test_preview_authority(
    db_session: Session, github: GitHub, kind: str, personal: bool
) -> None:
    actor = (
        make_user(db_session, standard_account=True)
        if kind == "ordinary"
        else manager(db_session, global_access=kind == "global")[0]
    )
    db_session.commit()
    with client_for(actor, db_session) as client:
        response = client.post(
            "/marketplaces/preview", json=SOURCE | {"personal": personal}
        )
    allowed = personal or kind == "global"
    assert response.status_code == (200 if allowed else 403), response.text
    assert bool(github.urls) == allowed


@pytest.mark.parametrize("revocation", ["manager", "basic", "inactive"])
def test_preview_rechecks_authority_after_provider_io(
    db_session: Session,
    github: GitHub,
    revocation: Revocation,
) -> None:
    actor = admin_with_basic(db_session)
    actor_id = actor.id
    db_session.commit()
    get = github.get

    def revoked(url: str, **kwargs: object) -> requests.Response:
        if "/tar.gz/" in url:
            revoke(actor_id, revocation)
        return get(url, **kwargs)

    with get_session_with_current_tenant() as auth_session:
        auth_user = auth_session.get(User, actor_id)
        assert auth_user is not None
        with (
            client_for(auth_user, db_session) as client,
            patch("onyx.utils.github.ssrf_safe_get", revoked),
        ):
            response = client.post(
                "/marketplaces/preview", json=SOURCE | {"personal": False}
            )
    assert response.status_code == 403, response.text
    assert len(github.urls) == 2


@pytest.mark.parametrize(
    "scopes", [[], [Permission.BASIC_ACCESS], [Permission.FULL_ADMIN_PANEL_ACCESS]]
)
def test_preview_token_cap(
    db_session: Session, github: GitHub, scopes: list[Permission]
) -> None:
    actor, _ = manager(db_session, global_access=True)
    db_session.commit()
    with client_for(actor, db_session, scopes) as client:
        response = client.post(
            "/marketplaces/preview", json=SOURCE | {"personal": False}
        )
    allowed = Permission.FULL_ADMIN_PANEL_ACCESS in scopes
    assert response.status_code == (200 if allowed else 403), response.text
    assert bool(github.urls) == allowed


@pytest.mark.parametrize(
    "extra",
    [
        {"login_user_id": "someone-else"},
        {"provider": "gitlab"},
        {
            "provider_config": {
                "owner": "acme",
                "repo": "tools",
                "ref": "main",
                "folder": "../bad",
            }
        },
    ],
)
def test_preview_rejects_invalid_input_before_network(
    db_session: Session, github: GitHub, extra: dict[str, object]
) -> None:
    actor = make_user(db_session, standard_account=True)
    db_session.commit()
    with client_for(actor, db_session) as client:
        response = client.post("/marketplaces/preview", json=SOURCE | extra)
    assert response.status_code == 422
    assert not github.urls


def test_preview_requires_connected_login(db_session: Session) -> None:
    actor = make_user(db_session, standard_account=True)
    db_session.commit()
    with (
        client_for(actor, db_session) as client,
        patch("onyx.utils.github.ssrf_safe_get") as network,
    ):
        response = client.post("/marketplaces/preview", json=SOURCE)
    assert response.status_code == 400, response.text
    network.assert_not_called()


@pytest.mark.parametrize("limited", [False, True])
def test_management_reads_respect_token_cap(db_session: Session, limited: bool) -> None:
    actor, _ = manager(db_session, global_access=True)
    other = make_user(db_session, standard_account=True)
    connect(db_session, actor)
    connect(db_session, other)
    personal = create(db_session, actor)
    company = create(db_session, actor, personal=False)
    foreign = create(db_session, other)
    personal_id, company_id, foreign_id = personal.id, company.id, foreign.id
    db_session.commit()
    scopes = [Permission.BASIC_ACCESS] if limited else None
    with client_for(actor, db_session, scopes) as client:
        response = client.get("/marketplaces")
        assert response.status_code == 200, response.text
        ids = {item["id"] for item in response.json()}
        assert str(personal_id) in ids
        assert (str(company_id) in ids) != limited
        assert (str(foreign_id) in ids) != limited
        assert not any(
            key in response.text
            for key in ("webhook_secret", "access_token", "user_credentials")
        )
        for identifier in (personal_id, company_id, foreign_id):
            response = client.get(f"/marketplaces/{identifier}")
            assert response.status_code == (
                404 if limited and identifier != personal_id else 200
            )
        assert client.get("/marketplaces/not-a-uuid").status_code == 422
    with client_for(other, db_session) as client:
        response = client.get("/marketplaces")
        assert {item["id"] for item in response.json()} == {str(foreign_id)}
        assert client.get(f"/marketplaces/{company_id}").status_code == 404
