from collections.abc import Iterator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from onyx.db.enums import AccountType, Permission
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage import users


def _user(email: str, account_type: AccountType = AccountType.STANDARD) -> User:
    return User(
        id=uuid4(),
        email=email,
        account_type=account_type,
        is_active=True,
        hashed_password="test-hash",
        personal_name=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        craft_enabled=None,
        effective_permissions=[Permission.FULL_ADMIN_PANEL_ACCESS.value],
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(users.router)
    caller = _user("manager@example.com")
    caller.effective_permissions = []
    caller.is_group_manager = True
    for route in app.routes:
        if isinstance(route, APIRoute):
            for dependency in route.dependant.dependencies:
                if dependency.name in {"current_user", "_"}:
                    assert dependency.call is not None
                    app.dependency_overrides[dependency.call] = lambda: caller
    app.dependency_overrides[users.get_session] = lambda: MagicMock()
    with TestClient(app) as test_client:
        yield test_client


def test_upsert_requires_integration_mode(client: TestClient) -> None:
    upsert = AsyncMock(return_value=None)
    with patch.object(users, "fetch_ee_implementation_or_noop", return_value=upsert):
        with patch.object(users, "INTEGRATION_TESTS_MODE", False, create=True):
            with pytest.raises(OnyxError) as exc:
                client.post(
                    "/manage/users/test-upsert-user", json={"email": "user@example.com"}
                )
            assert exc.value.status_code == 404
            upsert.assert_not_awaited()
        with patch.object(users, "INTEGRATION_TESTS_MODE", True, create=True):
            response = client.post(
                "/manage/users/test-upsert-user", json={"email": "user@example.com"}
            )
            assert response.status_code == 200
            upsert.assert_awaited_once_with(email="user@example.com")


@pytest.mark.usefixtures("enable_ee")
@pytest.mark.parametrize("paginated", [False, True])
def test_scoped_directory_redacts_privileged_fields(
    client: TestClient, paginated: bool
) -> None:
    accepted = _user("user@example.com")
    slack = _user("bot@example.com", AccountType.BOT)
    api_key = _user("API_KEY__test@example.com", AccountType.SERVICE_ACCOUNT)
    params = {"include_api_keys": "true"}
    if paginated:
        params.update(accepted_page="0", slack_users_page="0", invited_page="0")

    def roster(
        _db_session: object,
        email_filter_string: str | None,
        include_api_key_users: bool,
    ) -> list[User]:
        assert email_filter_string is None
        return (
            [accepted, slack, api_key] if include_api_key_users else [accepted, slack]
        )

    with (
        patch.object(users, "get_all_users", side_effect=roster),
        patch.object(users, "get_scoped_groups", return_value={1}),
        patch.object(users, "get_invited_users", return_value=["invite@example.com"]),
        patch.object(
            users,
            "batch_get_user_groups",
            return_value={
                user.id: [(1, "managed"), (2, "unmanaged")]
                for user in [accepted, slack, api_key]
            },
        ),
    ):
        response = client.get("/manage/users", params=params)
        assert response.status_code == 200
        data = response.json()
        assert [user["email"] for user in data["accepted"]] == [accepted.email]
        assert data["invited"] == []
        for user in data["accepted"] + data["slack_users"]:
            assert user["groups"] == [{"id": 1, "name": "managed"}]
            assert user["is_admin"] is False
        with patch.object(users, "has_global_permission", return_value=True):
            response = client.get("/manage/users", params=params)
            data = response.json()
            assert len(data["accepted"]) == 2
            assert data["invited"] == [{"email": "invite@example.com"}]
            for user in data["accepted"] + data["slack_users"]:
                assert len(user["groups"]) == 2
                assert user["is_admin"] is True
