from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from starlette.requests import Request

from onyx.cache.interface import CacheBackend
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build import static_preview as preview
from onyx.server.features.build.session.models import (
    OutputFileResponse,
    OutputInventoryResponse,
)
from shared_configs.contextvars import get_current_tenant_id


@pytest.fixture
def request_scope() -> Request:
    return Request(
        {
            "type": "http",
            "scheme": "http",
            "server": ("localhost", 3000),
            "path": "/",
            "query_string": b"",
            "headers": [],
        }
    )


@pytest.fixture
def setup_preview() -> Iterator[tuple[MagicMock, MagicMock, User, Session]]:
    cache = MagicMock(spec=CacheBackend)
    manager = MagicMock()
    user = User(id=uuid4(), is_active=True)
    db = MagicMock(spec=Session)
    manager.get_output_inventory.return_value = OutputInventoryResponse(
        complete=True,
        files=[
            OutputFileResponse(path=path, revision="1", size=100)
            for path in (
                "outputs/site/index.html",
                "outputs/site/style.css",
                "outputs/site/app.mjs",
                "outputs/site/images/icon.svg",
                "outputs/other/private.html",
                "outputs/site/.env",
                "outputs/site/passwords.txt",
            )
        ],
    )

    @contextmanager
    def tenant_session(*, tenant_id: str) -> Iterator[Session]:
        assert tenant_id == "preview_tenant"
        assert get_current_tenant_id() == tenant_id
        yield db

    with (
        patch.object(preview, "get_shared_cache_backend", return_value=cache),
        patch.object(preview, "SessionManager", return_value=manager),
        patch.object(preview, "get_current_tenant_id", return_value="preview_tenant"),
        patch.object(preview, "get_session_with_tenant", side_effect=tenant_session),
        patch.object(preview, "fetch_user_by_id", return_value=user),
        patch.object(preview, "get_build_session", return_value=MagicMock()),
        patch.object(preview, "has_global_permission", return_value=True),
        patch.object(preview, "is_craft_enabled_for_user", return_value=True),
    ):
        yield cache, manager, user, db


def test_grant_scopes_assets_and_expires(
    setup_preview: tuple[MagicMock, MagicMock, User, Session],
) -> None:
    cache, _, user, db = setup_preview
    result = preview.create_static_preview(uuid4(), "outputs/site/index.html", user, db)
    key, encoded = cache.set.call_args.args
    grant = preview.StaticPreviewGrant.model_validate_json(encoded)
    assert grant.root == "outputs/site/"
    assert grant.tenant_id == "preview_tenant"
    assert set(grant.files) == {"index.html", "style.css", "app.mjs", "images/icon.svg"}
    assert result.path.endswith("/index.html")
    assert key == f"craft:static-preview:{result.path.split('/')[0]}"
    assert cache.set.call_args.kwargs == {"ex": 3600}


@pytest.mark.parametrize(
    "path",
    [
        "uploads/index.html",
        "outputs/../index.html",
        "/outputs/index.html",
        "outputs/.private/index.html",
        "outputs/site/app.js",
    ],
)
def test_rejects_invalid_entrypoints(
    path: str, setup_preview: tuple[MagicMock, MagicMock, User, Session]
) -> None:
    cache, manager, user, db = setup_preview
    with pytest.raises(OnyxError):
        preview.create_static_preview(uuid4(), path, user, db)
    cache.set.assert_not_called()
    manager.get_output_inventory.assert_not_called()


def test_serves_assets_without_cookie_auth_and_restores_tenant(
    request_scope: Request,
    setup_preview: tuple[MagicMock, MagicMock, User, Session],
) -> None:
    cache, manager, user, db = setup_preview
    issued = preview.create_static_preview(uuid4(), "outputs/site/index.html", user, db)
    encoded = cache.set.call_args.args[1]
    cache.get.side_effect = lambda key: (
        encoded if key.startswith("craft:static-preview:") else None
    )
    manager.download_artifact.return_value = (
        b"export const value = 1",
        "application/octet-stream",
        "app.mjs",
    )
    before = get_current_tenant_id()
    response = preview.read_static_preview(
        issued.path.split("/")[0], "app.mjs", request_scope
    )
    assert get_current_tenant_id() == before
    assert response.media_type == "text/javascript"
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    csp = response.headers["content-security-policy"]
    assert "sandbox allow-scripts;" in csp
    assert "allow-same-origin" not in csp
    assert "default-src 'none'" in csp
    assert "base-uri 'none'" in csp
    assert "form-action 'none'" in csp


@pytest.mark.parametrize(
    "path",
    [
        "../other/private.html",
        "/index.html",
        "%2e%2e/other/private.html",
        "images/../../other/private.html",
        ".env",
        "passwords.txt",
    ],
)
def test_capability_rejects_unlisted_paths(
    request_scope: Request,
    path: str,
    setup_preview: tuple[MagicMock, MagicMock, User, Session],
) -> None:
    cache, manager, user, db = setup_preview
    preview.create_static_preview(uuid4(), "outputs/site/index.html", user, db)
    encoded = cache.set.call_args.args[1]
    cache.get.side_effect = lambda key: (
        encoded if key.startswith("craft:static-preview:") else None
    )
    with pytest.raises(OnyxError):
        preview.read_static_preview("token", path, request_scope)
    manager.download_artifact.assert_not_called()


def test_expired_token_and_disabled_owner_cannot_read(
    request_scope: Request,
    setup_preview: tuple[MagicMock, MagicMock, User, Session],
) -> None:
    cache, manager, user, db = setup_preview
    cache.get.return_value = None
    with pytest.raises(OnyxError):
        preview.read_static_preview("expired", "index.html", request_scope)
    preview.create_static_preview(uuid4(), "outputs/site/index.html", user, db)
    encoded = cache.set.call_args.args[1]
    cache.get.side_effect = lambda key: (
        encoded if key.startswith("craft:static-preview:") else None
    )
    user.is_active = False
    with pytest.raises(OnyxError):
        preview.read_static_preview("token", "index.html", request_scope)
    manager.download_artifact.assert_not_called()


def test_deleted_or_oversized_asset_is_not_read(
    request_scope: Request,
    setup_preview: tuple[MagicMock, MagicMock, User, Session],
) -> None:
    cache, manager, user, db = setup_preview
    preview.create_static_preview(uuid4(), "outputs/site/index.html", user, db)
    encoded = cache.set.call_args.args[1]
    cache.get.side_effect = lambda key: (
        encoded if key.startswith("craft:static-preview:") else None
    )
    for files in [
        [],
        [
            OutputFileResponse(
                path="outputs/site/index.html",
                revision="2",
                size=preview.MAX_ASSET_BYTES + 1,
            )
        ],
    ]:
        manager.get_output_inventory.return_value = OutputInventoryResponse(
            files=files, complete=True
        )
        with pytest.raises(OnyxError):
            preview.read_static_preview("token", "index.html", request_scope)
    manager.download_artifact.assert_not_called()


def test_cached_assets_skip_sandbox_reads_but_recheck_session_access(
    request_scope: Request,
    setup_preview: tuple[MagicMock, MagicMock, User, Session],
) -> None:
    cache, manager, user, db = setup_preview
    preview.create_static_preview(uuid4(), "outputs/site/index.html", user, db)
    encoded = cache.set.call_args.args[1]
    cache.get.side_effect = lambda key: (
        encoded if key.startswith("craft:static-preview:") else b"body {color: green}"
    )
    manager.reset_mock()
    response = preview.read_static_preview("token", "style.css", request_scope)
    assert response.body == b"body {color: green}"
    manager.get_output_inventory.assert_not_called()
    manager.download_artifact.assert_not_called()
    with patch.object(preview, "get_build_session", return_value=None):
        with pytest.raises(OnyxError):
            preview.read_static_preview("token", "style.css", request_scope)


def test_folder_total_size_is_bounded(
    setup_preview: tuple[MagicMock, MagicMock, User, Session],
) -> None:
    cache, manager, user, db = setup_preview
    manager.get_output_inventory.return_value = OutputInventoryResponse(
        complete=True,
        files=[
            OutputFileResponse(
                path=f"outputs/site/{name}", revision="1", size=preview.MAX_ASSET_BYTES
            )
            for name in ["index.html", "one.js", "two.js"]
        ],
    )
    with pytest.raises(OnyxError):
        preview.create_static_preview(uuid4(), "outputs/site/index.html", user, db)
    cache.set.assert_not_called()


def test_old_or_invalid_grants_fail_closed(
    request_scope: Request,
    setup_preview: tuple[MagicMock, MagicMock, User, Session],
) -> None:
    cache, manager, _, _ = setup_preview
    cache.get.return_value = b'{"files": ["index.html"]}'
    with pytest.raises(OnyxError):
        preview.read_static_preview("old", "index.html", request_scope)
    manager.download_artifact.assert_not_called()


def test_routes_pass_auth_registration_check() -> None:
    from fastapi import FastAPI

    from onyx.server.auth_check import check_router_auth

    app = FastAPI()
    app.include_router(preview.router, prefix="/build")
    app.include_router(preview.public_router)
    check_router_auth(app)


def test_reload_shares_unchanged_assets_but_reads_new_revisions(
    request_scope: Request,
    setup_preview: tuple[MagicMock, MagicMock, User, Session],
) -> None:
    cache, manager, user, db = setup_preview
    stored: dict[str, str | bytes] = {}
    cache.set.side_effect = lambda key, value, **_kwargs: stored.__setitem__(key, value)
    cache.get.side_effect = stored.get
    session_id = uuid4()
    manager.download_artifact.return_value = (b"first", "text/html", "index.html")
    first = preview.create_static_preview(
        session_id, "outputs/site/index.html", user, db
    )
    preview.read_static_preview(first.path.split("/")[0], "index.html", request_scope)
    second = preview.create_static_preview(
        session_id, "outputs/site/index.html", user, db
    )
    assert second.path != first.path
    preview.read_static_preview(second.path.split("/")[0], "index.html", request_scope)
    assert manager.download_artifact.call_count == 1
    manager.get_output_inventory.return_value.files[0].revision = "2"
    manager.download_artifact.return_value = (b"second", "text/html", "index.html")
    third = preview.create_static_preview(
        session_id, "outputs/site/index.html", user, db
    )
    response = preview.read_static_preview(
        third.path.split("/")[0], "index.html", request_scope
    )
    assert response.body == b"second"
    assert manager.download_artifact.call_count == 2
    assert len([key for key in stored if key.startswith("craft:static-asset:")]) == 2


def test_renewal_preserves_url_and_rejects_other_owners_and_sessions(
    setup_preview: tuple[MagicMock, MagicMock, User, Session],
) -> None:
    cache, _, user, db = setup_preview
    session_id = uuid4()
    issued = preview.create_static_preview(
        session_id, "outputs/site/index.html", user, db
    )
    encoded = cache.set.call_args.args[1]
    cache.get.return_value = encoded
    token = issued.path.split("/")[0]
    renewed = preview.create_static_preview(
        session_id, "outputs/site/index.html", user, db, token
    )
    assert renewed.path == issued.path
    assert cache.set.call_args.args[1] == encoded
    for other_session, other_user in [
        (uuid4(), user),
        (session_id, User(id=uuid4(), is_active=True)),
    ]:
        with pytest.raises(OnyxError):
            preview.create_static_preview(
                other_session, "outputs/site/index.html", other_user, db, token
            )
    cache.get.return_value = None
    with pytest.raises(OnyxError):
        preview.create_static_preview(
            session_id, "outputs/site/index.html", user, db, token
        )
