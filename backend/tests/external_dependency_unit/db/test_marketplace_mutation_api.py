"""Marketplace routes commit real PostgreSQL writes before controlled external work."""

from contextlib import ExitStack
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
import requests
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.marketplace_sync import tasks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.marketplace_sync import (
    MarketplaceSyncLeaseLost,
    claim_marketplace_sync,
    fence_marketplace_sync,
)
from onyx.db.models import FileRecord, Marketplace, Skill, SkillVersion, User
from onyx.server.features.skill import marketplace_api as api
from onyx.server.settings.models import Tier
from onyx.skills.marketplace.models import (
    MarketplaceRetirementProposal,
    MarketplaceSyncStatus,
)
from onyx.skills.sync import sync_marketplace
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.craft.db_helpers import make_sandbox, make_user
from tests.external_dependency_unit.db.test_marketplace_api import SOURCE, client_for
from tests.external_dependency_unit.db.test_marketplace_api import github as github
from tests.external_dependency_unit.db.test_marketplace_management import (
    connect,
    create,
)
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    apply,
    catalog,
    skills,
)
from tests.external_dependency_unit.db.test_marketplace_sync import GitHub
from tests.external_dependency_unit.db.test_marketplace_sync_tasks import (
    broker as broker,
)
from tests.external_dependency_unit.db.test_skill_access_actor import (
    Revocation,
    admin_with_basic,
    revoke,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import manager

pytestmark = pytest.mark.usefixtures("tenant_context", "enable_ee", "broker")


def test_create_commits_before_dispatch(
    db_session: Session, github: GitHub, broker: Mock
) -> None:
    actor = make_user(db_session, standard_account=True)
    connect(db_session, actor)
    actor_id = actor.id
    db_session.commit()
    get = github.get
    sent: list[UUID] = []

    def unlocked_get(url: str, **kwargs: object) -> requests.Response:
        assert not db_session.in_transaction()
        return get(url, **kwargs)

    def committed_send(_task: str, **_options: object) -> None:
        assert not db_session.in_transaction()
        with get_session_with_current_tenant() as observer:
            row = observer.scalar(
                select(Marketplace).where(Marketplace.owner_user_id == actor_id)
            )
            assert (
                row is not None and row.sync_requested and row.login_user_id == actor_id
            )
            assert row.sync_dispatch_after is not None
            assert not list(
                observer.scalars(select(Skill.id).where(Skill.marketplace_id == row.id))
            )
            sent.append(row.id)

    broker.side_effect = committed_send
    with (
        get_session_with_current_tenant() as auth_session,
        patch("onyx.utils.github.ssrf_safe_get", unlocked_get),
    ):
        actor = auth_session.get(User, actor_id)
        assert actor is not None
        with client_for(actor, db_session) as client:
            response = client.post(
                "/marketplaces", json=SOURCE | {"name": "  Team tools  "}
            )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["name"] == "Team tools" and data["sync_requested"]
    assert sent == [UUID(data["id"])] and len(github.urls) == 2
    assert data["owner_user_id"] == data["login_user_id"] == str(actor_id)


@pytest.mark.parametrize("bad", ["catalog", "disconnected", "name", "login"])
def test_create_rejects_invalid_source_without_writes(
    db_session: Session, github: GitHub, broker: Mock, bad: str
) -> None:
    actor = make_user(db_session, standard_account=True)
    if bad != "disconnected":
        connect(db_session, actor)
    db_session.commit()
    payload = SOURCE | {"name": "Tools"}
    if bad == "catalog":
        github.archive = b"invalid archive"
    elif bad == "name":
        payload["name"] = "   "
    elif bad == "login":
        payload["login_user_id"] = str(uuid4())
    with client_for(actor, db_session) as client:
        response = client.post("/marketplaces", json=payload)
    assert response.status_code == (422 if bad in {"name", "login"} else 400), (
        response.text
    )
    db_session.rollback()
    assert (
        db_session.scalar(
            select(Marketplace.id).where(Marketplace.owner_user_id == actor.id)
        )
        is None
    )
    broker.assert_not_called()


@pytest.mark.parametrize("scopes", [None, [Permission.BASIC_ACCESS]])
@pytest.mark.parametrize("global_actor", [False, True])
def test_create_company_requires_global_authority_and_token_scope(
    db_session: Session,
    github: GitHub,
    scopes: list[Permission] | None,
    global_actor: bool,
) -> None:
    actor, _ = manager(db_session, global_access=global_actor)
    connect(db_session, actor)
    db_session.commit()
    with client_for(actor, db_session, scopes) as client:
        response = client.post(
            "/marketplaces", json=SOURCE | {"name": "Company", "personal": False}
        )
    allowed = global_actor and scopes is None
    assert response.status_code == (200 if allowed else 403), response.text
    assert bool(github.urls) == allowed
    if allowed:
        assert response.json()["owner_user_id"] is None


@pytest.mark.parametrize(
    "operation", ["sync", "replace-login", "confirm-retirements", "delete"]
)
@pytest.mark.parametrize(
    "kind", ["owner", "other", "scoped", "global", "limited_global"]
)
def test_personal_mutation_authority(
    db_session: Session, github: GitHub, operation: str, kind: str
) -> None:
    owner = make_user(db_session, standard_account=True)
    actor = (
        owner
        if kind == "owner"
        else (
            make_user(db_session, standard_account=True)
            if kind == "other"
            else manager(db_session, global_access=kind != "scoped")[0]
        )
    )
    connect(db_session, owner)
    if actor.id != owner.id:
        connect(db_session, actor)
    row = create(db_session, owner)
    row.sync_requested = False
    row.sync_status = MarketplaceSyncStatus.NEEDS_CONFIRMATION
    proposal = MarketplaceRetirementProposal(revision="b" * 40, skill_ids=(uuid4(),))
    row.retirement_proposal = proposal
    identifier = row.id
    db_session.commit()
    scopes = [Permission.BASIC_ACCESS] if kind == "limited_global" else None
    with client_for(actor, db_session, scopes) as client:
        response = (
            client.delete(f"/marketplaces/{identifier}")
            if operation == "delete"
            else client.post(
                f"/marketplaces/{identifier}/{operation}",
                json={
                    "revision": proposal.revision,
                    "skill_ids": [str(i) for i in proposal.skill_ids],
                }
                if operation == "confirm-retirements"
                else None,
            )
        )
    allowed = kind in {"owner", "global"}
    expected = 200 if allowed else 403 if kind == "global" else 404
    assert response.status_code == expected, response.text
    assert bool(github.urls) == (allowed and operation == "replace-login")
    db_session.rollback()
    stored = db_session.get(Marketplace, identifier, populate_existing=True)
    if operation == "delete" and allowed:
        assert stored is None
    else:
        assert stored is not None and stored.sync_requested == allowed


@pytest.mark.parametrize(
    "operation", ["sync", "replace-login", "confirm-retirements", "delete", "access"]
)
@pytest.mark.parametrize("kind", ["scoped", "limited_global", "global"])
def test_company_mutation_authority(
    db_session: Session, github: GitHub, operation: str, kind: str
) -> None:
    owner, _ = manager(db_session, global_access=True)
    actor, _ = manager(db_session, global_access=kind != "scoped")
    connect(db_session, owner)
    connect(db_session, actor)
    row = create(db_session, owner, personal=False)
    row.sync_status = MarketplaceSyncStatus.NEEDS_CONFIRMATION
    proposal = MarketplaceRetirementProposal(revision="b" * 40, skill_ids=(uuid4(),))
    row.retirement_proposal = proposal
    identifier = row.id
    db_session.commit()
    scopes = [Permission.BASIC_ACCESS] if kind == "limited_global" else None
    with (
        client_for(actor, db_session, scopes) as client,
        patch.object(api, "get_current_tier", return_value=Tier.BUSINESS),
    ):
        if operation == "access":
            response = client.patch(
                f"/marketplaces/{identifier}/access",
                json={"public_permission": "VIEWER"},
            )
        elif operation == "delete":
            response = client.delete(f"/marketplaces/{identifier}")
        else:
            response = client.post(
                f"/marketplaces/{identifier}/{operation}",
                json={
                    "revision": proposal.revision,
                    "skill_ids": [str(i) for i in proposal.skill_ids],
                }
                if operation == "confirm-retirements"
                else None,
            )
    assert response.status_code == (
        200 if kind == "global" else 403 if operation == "access" else 404
    ), response.text

    assert bool(github.urls) == (kind == "global" and operation == "replace-login")


@pytest.mark.parametrize("revocation", ["manager", "basic", "inactive"])
def test_replace_rechecks_actor_after_network(
    db_session: Session, github: GitHub, broker: Mock, revocation: Revocation
) -> None:
    actor = admin_with_basic(db_session)
    connect(db_session, actor)
    row = create(db_session, actor, personal=False)
    row.sync_requested = False
    identifier, actor_id = row.id, actor.id
    db_session.commit()
    get = github.get

    def revoked(url: str, **kwargs: object) -> requests.Response:
        assert not db_session.in_transaction()
        revoke(actor_id, revocation)
        return get(url, **kwargs)

    with get_session_with_current_tenant() as auth_session:
        auth_user = auth_session.get(User, actor_id)
        assert auth_user is not None
        with (
            client_for(auth_user, db_session) as client,
            patch("onyx.utils.github.ssrf_safe_get", revoked),
        ):
            response = client.post(f"/marketplaces/{identifier}/replace-login")
    assert response.status_code == 403, response.text
    broker.assert_not_called()
    db_session.rollback()
    db_session.refresh(row)
    assert not row.sync_requested


def test_replace_preserves_history_and_fences_worker(
    db_session: Session, github: GitHub
) -> None:
    owner = make_user(db_session, standard_account=True)
    actor, _ = manager(db_session, global_access=True)
    connect(db_session, owner)
    connect(db_session, actor)
    row = create(db_session, owner)
    apply(db_session, row, catalog("first"))
    apply(db_session, row, catalog("first", body=b"changed"), revision="second")
    skill = skills(db_session, row)[0]
    identifier, skill_id, version_id, owner_id = (
        row.id,
        skill.id,
        skill.current_version_id,
        owner.id,
    )
    row.sync_status = MarketplaceSyncStatus.NEEDS_CONFIRMATION
    row.last_error = "needs confirmation"
    row.retirement_proposal = MarketplaceRetirementProposal(
        revision="next", skill_ids=(skill_id,)
    )
    db_session.commit()
    old_worker = claim_marketplace_sync(identifier, db_session)
    assert old_worker is not None
    versions = list(
        db_session.scalars(
            select(SkillVersion.id).where(SkillVersion.skill_id == skill_id)
        )
    )
    db_session.commit()
    with client_for(actor, db_session) as client:
        response = client.post(f"/marketplaces/{identifier}/replace-login")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["login_user_id"] == str(actor.id) and data["owner_user_id"] == str(
        owner_id
    )
    assert data["sync_status"] is None and data["last_error"] is None
    assert data["retirement_proposal"] is None
    # The applied revision stays, so the next sync reads "next" and proposes again.
    assert data["last_synced_revision"] == "second"
    assert data["provider_config"] == row.provider_config.model_dump(mode="json")
    db_session.refresh(skill)
    assert skill.current_version_id == version_id
    assert set(
        db_session.scalars(
            select(SkillVersion.id).where(SkillVersion.skill_id == skill_id)
        )
    ) == set(versions)
    with (
        get_session_with_current_tenant() as worker,
        pytest.raises(MarketplaceSyncLeaseLost),
    ):
        fence_marketplace_sync(identifier, old_worker, worker)
    assert len(github.urls) == 1


def test_confirmation_and_request_commit_together(
    db_session: Session, broker: Mock
) -> None:
    actor = make_user(db_session, standard_account=True)
    connect(db_session, actor)
    row = create(db_session, actor)
    apply(db_session, row, catalog(*(f"skill-{i}" for i in range(8))))
    apply(db_session, row, catalog("skill-7"), revision="next")
    proposal = row.retirement_proposal
    assert proposal is not None
    row.sync_requested = False
    identifier = row.id
    db_session.commit()

    def committed_send(_task: str, **_options: object) -> None:
        with get_session_with_current_tenant() as observer:
            stored = observer.get(Marketplace, identifier)
            assert stored is not None and stored.sync_requested
            assert (
                stored.retirement_proposal is not None
                and stored.retirement_proposal.approved
            )

    broker.side_effect = committed_send
    payload = {
        "revision": proposal.revision,
        "skill_ids": [str(i) for i in proposal.skill_ids],
    }
    with client_for(actor, db_session) as client:
        assert (
            client.post(
                f"/marketplaces/{identifier}/confirm-retirements",
                json=payload | {"revision": "stale"},
            ).status_code
            == 409
        )
        broker.assert_not_called()
        db_session.rollback()
        response = client.post(
            f"/marketplaces/{identifier}/confirm-retirements", json=payload
        )
    assert response.status_code == 200, response.text
    broker.assert_called_once()


@pytest.mark.parametrize("failure", ["commit", "broker", "reservation"])
def test_sync_durable_intent_on_failure(
    db_session: Session, broker: Mock, failure: str
) -> None:
    actor = make_user(db_session, standard_account=True)
    connect(db_session, actor)
    row = create(db_session, actor)
    row.sync_requested = False
    identifier = row.id
    db_session.commit()
    if failure == "broker":
        broker.side_effect = RuntimeError("broker down")
    target = db_session if failure == "commit" else api
    attribute = "commit" if failure == "commit" else "dispatch_marketplace_sync"
    with client_for(actor, db_session) as client:
        if failure == "broker":
            response = client.post(f"/marketplaces/{identifier}/sync")
            assert response.status_code == 200, response.text
        else:
            with patch.object(
                target, attribute, side_effect=RuntimeError("unavailable")
            ):
                if failure == "commit":
                    with pytest.raises(RuntimeError, match="unavailable"):
                        client.post(f"/marketplaces/{identifier}/sync")
                else:
                    assert (
                        client.post(f"/marketplaces/{identifier}/sync").status_code
                        == 200
                    )
    db_session.rollback()
    with get_session_with_current_tenant() as observer:
        stored = observer.get(Marketplace, identifier)
        assert stored is not None and stored.sync_requested == (failure != "commit")
    if failure != "broker":
        broker.assert_not_called()


@pytest.mark.parametrize("case", ["idle", "busy", "reservation", "uncertain_commit"])
def test_sync_marks_activity_before_saving_intent(
    db_session: Session, broker: Mock, case: str
) -> None:
    actor = make_user(db_session, standard_account=True)
    connect(db_session, actor)
    row = create(db_session, actor)
    identifier, actor_id = row.id, actor.id
    db_session.commit()
    if case == "busy":
        assert claim_marketplace_sync(identifier, db_session) is not None
    commit = db_session.commit

    def mark(tenant_id: str, *, caller: str) -> None:
        assert not db_session.in_transaction()
        assert tenant_id == get_current_tenant_id() and caller == "marketplace_sync"

    def uncertain_commit() -> None:
        commit()
        raise RuntimeError("commit acknowledgement lost")

    with (
        get_session_with_current_tenant() as auth_session,
        ExitStack() as patches,
        patch.object(api, "maybe_mark_tenant_active", side_effect=mark) as activity,
    ):
        auth_user = auth_session.get(User, actor_id)
        assert auth_user is not None
        if case == "reservation":
            patches.enter_context(
                patch.object(
                    tasks, "reserve_marketplace_dispatches", side_effect=RuntimeError
                )
            )
        elif case == "uncertain_commit":
            patches.enter_context(
                patch.object(db_session, "commit", side_effect=uncertain_commit)
            )
        with client_for(auth_user, db_session) as client:
            if case == "uncertain_commit":
                with pytest.raises(RuntimeError, match="commit acknowledgement lost"):
                    client.post(f"/marketplaces/{identifier}/sync")
            else:
                response = client.post(f"/marketplaces/{identifier}/sync")
                assert response.status_code == 200, response.text
    activity.assert_called_once()
    with get_session_with_current_tenant() as observer:
        stored = observer.get(Marketplace, identifier)
        assert stored is not None and stored.sync_requested
    assert broker.call_count == (1 if case == "idle" else 0)


def test_access_updates_followers_and_pushes_after_commit(db_session: Session) -> None:
    actor, group = manager(db_session, global_access=True)
    connect(db_session, actor)
    row = create(db_session, actor, personal=False)
    suffix = uuid4().hex[:8]
    apply(db_session, row, catalog(f"api-follower-{suffix}", f"api-override-{suffix}"))
    follower, override = sorted(skills(db_session, row), key=lambda s: s.name)
    override.follows_marketplace_access = False
    identifier, follower_id, override_id = row.id, follower.id, override.id
    make_sandbox(db_session, actor)
    db_session.commit()

    def published(affected: set[UUID], _session: Session) -> None:
        assert actor.id in affected
        with get_session_with_current_tenant() as observer:
            current = observer.get(Skill, follower_id)
            unchanged = observer.get(Skill, override_id)
            assert (
                current is not None and current.group_shares[0].user_group_id == group
            )
            assert unchanged is not None and not unchanged.group_shares

    with (
        client_for(actor, db_session) as client,
        patch.object(api, "get_current_tier", return_value=Tier.BUSINESS),
        patch.object(api, "push_skills_for_users", side_effect=published) as push,
    ):
        response = client.patch(
            f"/marketplaces/{identifier}/access",
            json={"group_shares": [{"group_id": group, "permission": "VIEWER"}]},
        )
        assert response.status_code == 200, response.text
        push.assert_called_once()
        assert (
            client.patch(
                f"/marketplaces/{identifier}/access",
                json={
                    "user_shares": [{"user_id": str(actor.id), "permission": "EDITOR"}]
                },
            ).status_code
            == 422
        )


def test_remove_deletes_skills_and_bundles_after_commit(
    db_session: Session, github: GitHub
) -> None:
    actor = make_user(db_session, standard_account=True)
    connect(db_session, actor)
    make_sandbox(db_session, actor)
    row = create(db_session, actor)
    identifier = row.id
    db_session.commit()
    sync_marketplace(identifier, get_current_tenant_id())
    assert len(github.urls) == 2
    current = list(
        db_session.scalars(select(Skill).where(Skill.marketplace_id == identifier))
    )
    skill_ids = [skill.id for skill in current]
    bundle_ids = [skill.bundle_file_id for skill in current]
    db_session.commit()

    def published(affected: set[UUID], _session: Session) -> None:
        assert actor.id in affected
        with get_session_with_current_tenant() as observer:
            assert observer.get(Marketplace, identifier) is None
            assert not list(
                observer.scalars(select(Skill.id).where(Skill.id.in_(skill_ids)))
            )
        raise RuntimeError("push unavailable")

    with (
        client_for(actor, db_session) as client,
        patch.object(api, "push_skills_for_users", side_effect=published) as push,
    ):
        response = client.delete(f"/marketplaces/{identifier}")
    assert response.status_code == 200, response.text
    push.assert_called_once()
    assert not list(
        db_session.scalars(
            select(SkillVersion.id).where(SkillVersion.skill_id.in_(skill_ids))
        )
    )
    assert not list(
        db_session.scalars(
            select(FileRecord.file_id).where(FileRecord.file_id.in_(bundle_ids))
        )
    )


def test_reads_and_preview_do_not_serialize_membership_writes(
    db_session: Session, github: GitHub
) -> None:
    from sqlalchemy import text

    from onyx.db.users import lock_group_membership

    actor = make_user(db_session, standard_account=True)
    connect(db_session, actor)
    row = create(db_session, actor)
    identifier = row.id
    db_session.commit()
    with get_session_with_current_tenant() as writer:
        lock_group_membership(writer)
        db_session.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with client_for(actor, db_session) as client:
            assert client.get("/marketplaces").status_code == 200
            assert client.get(f"/marketplaces/{identifier}").status_code == 200
            assert client.post("/marketplaces/preview", json=SOURCE).status_code == 200
        writer.rollback()
    assert len(github.urls) == 2
    with client_for(actor, db_session) as client:
        assert client.get("/marketplaces").status_code == 200
        with get_session_with_current_tenant() as writer:
            lock_group_membership(writer, nowait=True)


def test_admin_removes_deactivated_owners_source_before_user_deletion(
    db_session: Session,
) -> None:
    from onyx.db.users import delete_user_from_db__no_commit

    owner = make_user(db_session, standard_account=True)
    admin, _ = manager(db_session, global_access=True)
    connect(db_session, owner)
    row = create(db_session, owner)
    apply(db_session, row, catalog("first"))
    owner.is_active = False
    identifier, owner_id = row.id, owner.id
    db_session.commit()
    with client_for(admin, db_session) as client:
        response = client.delete(f"/marketplaces/{identifier}")
    assert response.status_code == 200, response.text
    delete_user_from_db__no_commit(owner, db_session)
    db_session.commit()
    with get_session_with_current_tenant() as observer:
        assert observer.get(User, owner_id) is None
        assert observer.get(Marketplace, identifier) is None


def test_only_creation_and_preview_accept_source_config() -> None:
    config_routes = set()
    for route in api.router.routes:
        assert isinstance(route, APIRoute)
        for param in route.dependant.body_params:
            annotation = param.field_info.annotation
            if (
                isinstance(annotation, type)
                and issubclass(annotation, BaseModel)
                and "provider_config" in annotation.model_fields
            ):
                config_routes.add(route.path)
    assert config_routes == {"/marketplaces", "/marketplaces/preview"}
