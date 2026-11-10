"""Webhook setup saves signing state before GitHub I/O and rechecks authority."""

import hashlib
import hmac
import json
from collections.abc import Generator
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.marketplace_webhook import receive_marketplace_webhook__no_commit
from onyx.db.models import Marketplace, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill import marketplace_api as api
from onyx.skills.marketplace.models import GitHubMarketplaceConfig
from onyx.skills.marketplace.provider import GitHubMarketplaceAdapter
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.db.test_marketplace_api import client_for
from tests.external_dependency_unit.db.test_marketplace_management import (
    connect,
    create,
)
from tests.external_dependency_unit.db.test_skill_access_actor import admin_with_basic

pytestmark = pytest.mark.usefixtures("tenant_context", "enable_ee")


@pytest.fixture(autouse=True)
def configuration() -> Generator[None, None, None]:
    with (
        patch.object(api, "MULTI_TENANT", False),
        patch.object(api, "MARKETPLACE_WEBHOOK_BASE_URL", "https://onyx.example"),
    ):
        yield


@pytest.fixture
def actor(db_session: Session) -> User:
    user = make_user(db_session, standard_account=True)
    connect(db_session, user)
    db_session.commit()
    return user


@pytest.fixture
def source(db_session: Session, actor: User) -> Marketplace:
    row = create(db_session, actor)
    db_session.commit()
    return row


@pytest.fixture
def resolution() -> Generator[Mock, None, None]:
    with patch.object(
        GitHubMarketplaceAdapter, "resolve_webhook_ref", return_value="refs/heads/main"
    ) as call:
        yield call


@pytest.fixture
def registration() -> Generator[Mock, None, None]:
    with patch.object(
        GitHubMarketplaceAdapter, "register_webhook", autospec=True, return_value="17"
    ) as call:
        yield call


def test_first_ping_and_retry_use_committed_signing_state(
    db_session: Session,
    actor: User,
    source: Marketplace,
    resolution: Mock,
    registration: Mock,
) -> None:
    secrets_seen: list[str] = []

    def register(adapter: GitHubMarketplaceAdapter, callback: str) -> str:
        assert not db_session.in_transaction()
        assert (
            callback == f"https://onyx.example/webhook/marketplaces/{source.id}/github"
        )
        with get_session_with_current_tenant() as observer:
            saved = observer.get(Marketplace, source.id)
            assert saved is not None and saved.webhook_secret is not None
            secret = saved.webhook_secret.get_value(apply_mask=False)
            assert adapter.marketplace.webhook_secret is not None
            assert (
                adapter.marketplace.webhook_secret.get_value(apply_mask=False) == secret
            )
            secrets_seen.append(secret)
            body = json.dumps({"repository": {"full_name": "acme/tools"}}).encode()
            signature = (
                "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            )
            assert not receive_marketplace_webhook__no_commit(
                source.id,
                body,
                signature=signature,
                event="ping",
                hook_id="17",
                db_session=observer,
            )
            observer.commit()
        return "17"

    registration.side_effect = register
    resolution.side_effect = lambda: (
        "refs/heads/main"
        if not db_session.in_transaction()
        else pytest.fail("Resolution held a transaction")
    )
    with client_for(actor, db_session) as client:
        for attempt in range(2):
            result = client.post(f"/marketplaces/{source.id}/webhook")
            assert result.status_code == 200, result.text
            assert result.json()["webhook_enabled"]
            assert result.json()["webhook_ref"] == "refs/heads/main"
            assert (result.json()["webhook_last_delivery_at"] is not None) == (
                attempt > 0
            )
            assert "webhook_secret" not in result.json()
            assert secrets_seen[-1] not in result.text
    assert len(secrets_seen) == 2 and secrets_seen[0] == secrets_seen[1]


def test_registration_failure_keeps_manual_sync(
    db_session: Session,
    actor: User,
    source: Marketplace,
    resolution: Mock,
    registration: Mock,
) -> None:
    registration.side_effect = OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS, "Repository admin required"
    )
    with (
        client_for(actor, db_session) as client,
        patch.object(api, "dispatch_marketplace_sync"),
    ):
        result = client.post(f"/marketplaces/{source.id}/webhook")
        assert result.status_code == 403
        assert "Repository admin" in result.text
        result = client.post(f"/marketplaces/{source.id}/sync")
        assert result.status_code == 200, result.text
        assert not result.json()["webhook_enabled"] and result.json()["sync_pending"]
    resolution.assert_called_once()
    db_session.refresh(source)
    assert source.webhook_id is None and source.webhook_secret is not None


@pytest.mark.parametrize("outcome", ["success", "revoked", "provider_error"])
def test_pushes_require_completed_registration(
    db_session: Session,
    actor: User,
    source: Marketplace,
    resolution: Mock,
    registration: Mock,
    outcome: str,
) -> None:
    source.sync_requested = False
    db_session.commit()

    def push() -> bool:
        with get_session_with_current_tenant() as observer:
            row = observer.get(Marketplace, source.id)
            assert row is not None and row.webhook_secret is not None
            body = json.dumps(
                {"repository": {"full_name": "acme/tools"}, "ref": "refs/heads/main"}
            ).encode()
            secret = row.webhook_secret.get_value(apply_mask=False)
            signature = (
                "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            )
            queued = receive_marketplace_webhook__no_commit(
                source.id,
                body,
                signature=signature,
                event="push",
                hook_id="17",
                db_session=observer,
            )
            observer.commit()
            assert row.sync_requested == queued
            return queued

    def register(_adapter: GitHubMarketplaceAdapter, _callback: str) -> str:
        assert not push()
        if outcome == "revoked":
            with get_session_with_current_tenant() as observer:
                observer.execute(
                    update(User)
                    .where(User.__table__.c.id == actor.id)
                    .values(is_active=False)
                )
                observer.commit()
        elif outcome == "provider_error":
            raise OnyxError(OnyxErrorCode.BAD_GATEWAY, "Registration response lost")
        return "17"

    registration.side_effect = register
    with client_for(actor, db_session) as client:
        result = client.post(f"/marketplaces/{source.id}/webhook")
        assert (
            result.status_code
            == {
                "success": 200,
                "revoked": 403,
                "provider_error": 502,
            }[outcome]
        ), result.text
    db_session.rollback()
    assert push() == (outcome == "success")
    resolution.assert_called_once()


@pytest.mark.parametrize(
    "change", ["login", "ref", "secret", "inactive", "delete", "delete_cleanup_failed"]
)
def test_changes_during_provider_io_cannot_complete(
    db_session: Session,
    actor: User,
    source: Marketplace,
    resolution: Mock,
    registration: Mock,
    change: str,
) -> None:
    def register(_adapter: GitHubMarketplaceAdapter, _callback: str) -> str:
        assert not db_session.in_transaction()
        with get_session_with_current_tenant() as observer:
            row = observer.get(Marketplace, source.id)
            assert row is not None
            if change == "login":
                row.login_user_id = None
            elif change == "ref":
                row.provider_config = GitHubMarketplaceConfig(
                    owner="acme", repo="tools", ref="other"
                )
            elif change == "secret":
                row.webhook_secret = None
            elif change == "inactive":
                observer.execute(
                    update(User)
                    .where(User.__table__.c.id == actor.id)
                    .values(is_active=False)
                )
            else:
                observer.delete(row)
            observer.commit()
        return "17"

    registration.side_effect = register
    identifier = source.id

    def remove(adapter: GitHubMarketplaceAdapter) -> None:
        assert not db_session.in_transaction()
        assert adapter.marketplace.webhook_id == "17"
        if change == "delete_cleanup_failed":
            raise OnyxError(OnyxErrorCode.BAD_GATEWAY, "Provider unavailable")

    with (
        patch.object(
            GitHubMarketplaceAdapter,
            "remove_webhook",
            autospec=True,
            side_effect=remove,
        ) as cleanup,
        client_for(actor, db_session) as client,
    ):
        result = client.post(f"/marketplaces/{source.id}/webhook")
        assert result.status_code == (
            403 if change == "inactive" else 404 if change.startswith("delete") else 409
        ), result.text
    assert cleanup.call_count == int(change.startswith("delete"))
    resolution.assert_called_once()
    db_session.rollback()
    assert (
        db_session.scalar(
            select(Marketplace.webhook_id).where(Marketplace.id == identifier)
        )
        is None
    )


def test_source_change_during_resolution_stops_registration(
    db_session: Session,
    actor: User,
    source: Marketplace,
    resolution: Mock,
    registration: Mock,
) -> None:
    def resolve() -> str:
        with get_session_with_current_tenant() as observer:
            observer.execute(
                update(Marketplace)
                .where(Marketplace.id == source.id)
                .values(login_user_id=None)
            )
            observer.commit()
        return "refs/heads/main"

    resolution.side_effect = resolve
    with client_for(actor, db_session) as client:
        result = client.post(f"/marketplaces/{source.id}/webhook")
        assert result.status_code == 409
    registration.assert_not_called()


@pytest.mark.parametrize("limited", [False, True])
def test_other_users_and_limited_admin_tokens_cannot_register(
    db_session: Session,
    source: Marketplace,
    resolution: Mock,
    registration: Mock,
    limited: bool,
) -> None:
    other = (
        admin_with_basic(db_session)
        if limited
        else make_user(db_session, standard_account=True)
    )
    db_session.commit()
    with client_for(
        other, db_session, [Permission.BASIC_ACCESS] if limited else None
    ) as client:
        result = client.post(f"/marketplaces/{source.id}/webhook")
        assert result.status_code == 404, result.text
    resolution.assert_not_called()
    registration.assert_not_called()


@pytest.mark.parametrize("cloud", [True, False])
def test_cloud_or_unconfigured_public_url(
    db_session: Session,
    actor: User,
    source: Marketplace,
    resolution: Mock,
    registration: Mock,
    cloud: bool,
) -> None:
    with (
        patch.object(api, "MULTI_TENANT", cloud),
        patch.object(api, "MARKETPLACE_WEBHOOK_BASE_URL", None),
        client_for(actor, db_session) as client,
    ):
        result = client.post(f"/marketplaces/{source.id}/webhook")
        assert result.status_code == (404 if cloud else 400)
    resolution.assert_not_called()
    registration.assert_not_called()


@pytest.mark.parametrize("personal", [True, False])
def test_global_manager_can_configure_personal_and_company_sources(
    db_session: Session,
    actor: User,
    resolution: Mock,
    registration: Mock,
    personal: bool,
) -> None:
    admin = admin_with_basic(db_session)
    connect(db_session, admin)
    row = create(db_session, actor if personal else admin, personal=personal)
    db_session.commit()
    with client_for(admin, db_session) as client:
        result = client.post(f"/marketplaces/{row.id}/webhook")
        assert result.status_code == 200, result.text
        assert result.json()["webhook_enabled"]
    resolution.assert_called_once()
    registration.assert_called_once()


@pytest.mark.parametrize(
    "url",
    [
        "http://onyx.example",
        "https://[bad",
        "https://onyx.example:bad",
        "https://user:password@onyx.example",
        "https://onyx.example?query=1",
        "https://onyx.example#fragment",
        "https://onyx.example/webhook",
        "https://onyx.example/prefix/",
        "https://onyx.example/%2f",
        "https://localhost",
        "https://127.0.0.1",
    ],
)
def test_invalid_public_url_disables_setup(url: str) -> None:
    assert api._public_webhook_base_url(url) is None


@pytest.mark.parametrize("url", ["https://onyx.example", "https://onyx.example/"])
def test_public_origin_keeps_one_callback_prefix(url: str) -> None:
    assert api._public_webhook_base_url(url) == "https://onyx.example"
