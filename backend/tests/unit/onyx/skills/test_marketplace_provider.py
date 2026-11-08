from contextlib import nullcontext
from unittest.mock import MagicMock, patch
from urllib.parse import quote
from uuid import uuid4

import pytest
import requests
from pydantic import ValidationError

from onyx.db.models import Marketplace
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.github_auth import github_authorization_header
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from onyx.skills.marketplace.provider import get_marketplace_adapter
from onyx.utils.github import GitHubSource, resolve_github_revision


@pytest.mark.parametrize("folder", [None, "", "catalog", "catalog/", "a/b///"])
def test_marketplace_and_import_normalize_the_same_folder(folder: str | None) -> None:
    config = GitHubMarketplaceConfig(
        owner="acme", repo="skills", ref="main", folder=folder
    )
    resolved = resolve_github_revision(
        GitHubSource(owner="acme", repo="skills"), revision="a" * 40, subpath=folder
    )
    assert config.folder == resolved.subpath


@pytest.mark.parametrize("folder", ["/", "/catalog", "../x", "a//b", "a/../b", "a\\b"])
def test_marketplace_and_import_reject_the_same_folder(folder: str) -> None:
    with pytest.raises(ValidationError):
        GitHubMarketplaceConfig(owner="acme", repo="skills", ref="main", folder=folder)
    with pytest.raises(OnyxError):
        resolve_github_revision(
            GitHubSource(owner="acme", repo="skills"),
            revision="a" * 40,
            subpath=folder,
        )


@pytest.mark.parametrize("ref", ["feature/skills", "v1.0.0", "A" * 40])
def test_fetch_pins_branch_tag_and_commit(ref: str) -> None:
    marketplace = Marketplace(
        provider=MarketplaceProvider.GITHUB,
        provider_config=GitHubMarketplaceConfig(
            owner="acme", repo="skills", folder="catalog", ref=ref
        ),
        login_user_id=uuid4(),
    )
    commit = MagicMock(spec=requests.Response)
    commit.status_code = 200
    commit.headers = {}
    commit.json.return_value = {"sha": "a" * 40}
    commit.__enter__.return_value = commit
    archive = MagicMock(spec=requests.Response)
    archive.status_code = 200
    archive.iter_content.return_value = [b"archive"]
    archive.__enter__.return_value = archive
    with (
        patch(
            "onyx.skills.marketplace.provider.github_authorization_header",
            return_value="Bearer test",
        ) as login,
        patch(
            "onyx.utils.github.ssrf_safe_get",
            side_effect=[commit, archive, commit, commit],
        ) as fetch,
    ):
        adapter = get_marketplace_adapter(marketplace, "public")
        result = adapter.fetch_if_changed()
        assert result is not None
        assert result.revision == "a" * 40
        assert result.archive_bytes == b"archive"
        assert result.folder == "catalog"
        assert (
            fetch.call_args_list[0].args[0].endswith("/commits/" + quote(ref, safe=""))
        )
        assert fetch.call_args_list[1].args[0].endswith("/tar.gz/" + "a" * 40)
        marketplace.last_synced_revision = result.revision
        assert adapter.fetch_if_changed() is None
        assert adapter.resolve_revision() == result.revision
        assert fetch.call_count == 4
        login.assert_called_with(
            "public", marketplace.login_user_id, require_user_connection=True
        )
        assert not adapter.supports_webhooks


def test_missing_login_stops_before_fetch() -> None:
    marketplace = Marketplace(provider=MarketplaceProvider.GITHUB, login_user_id=None)
    with patch("onyx.utils.github.ssrf_safe_get") as fetch:
        with pytest.raises(OnyxError, match="Replace the login") as error:
            get_marketplace_adapter(marketplace, "public").fetch_if_changed()
        assert error.value.status_code == 400
        fetch.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner", "x/y"),
        ("owner", "."),
        ("owner", ".."),
        ("repo", "."),
        ("repo", ".."),
        ("repo", ""),
        ("folder", "../x"),
        ("folder", "/x"),
        ("ref", ""),
        ("ref", "main~1"),
        ("ref", "x..y"),
    ],
)
def test_invalid_provider_config(field: str, value: str) -> None:
    config = {"owner": "acme", "repo": "skills", "ref": "main", field: value}
    with pytest.raises(ValidationError):
        GitHubMarketplaceConfig.model_validate(config)


@pytest.mark.parametrize(
    "state",
    ["inactive", "disconnected", "revoked", "connected", "missing_app", "disabled_app"],
)
def test_marketplace_requires_active_personal_github_login(state: str) -> None:
    user_id = uuid4()
    app = (
        None
        if state == "missing_app"
        else MagicMock(id=1, enabled=state != "disabled_app")
    )
    credential = MagicMock()
    with (
        patch(
            "onyx.skills.github_auth.get_session_with_tenant",
            side_effect=lambda **_: nullcontext(MagicMock()),
        ),
        patch("onyx.skills.github_auth.get_built_in_external_app", return_value=app),
        patch(
            "onyx.skills.github_auth.fetch_user_by_id",
            return_value=MagicMock(is_active=state != "inactive"),
        ),
        patch(
            "onyx.skills.github_auth.get_external_app_user_credential",
            side_effect=[
                None if state == "disconnected" else credential,
                None if state == "revoked" else credential,
            ],
        ),
        patch("onyx.skills.github_auth.ensure_fresh_credentials") as refresh,
        patch(
            "onyx.skills.github_auth.resolve_injection_headers",
            return_value={"Authorization": "Bearer test"},
        ),
    ):
        if state == "connected":
            assert (
                github_authorization_header(
                    "public", user_id, require_user_connection=True
                )
                == "Bearer test"
            )
            refresh.assert_called_once_with("public", 1, user_id)
        else:
            with pytest.raises(
                OnyxError,
                match="Enable the GitHub app"
                if state.endswith("_app")
                else "Replace the login",
            ) as error:
                github_authorization_header(
                    "public", user_id, require_user_connection=True
                )
            assert error.value.status_code == 400
            if state in {"inactive", "disconnected", "missing_app", "disabled_app"}:
                refresh.assert_not_called()


def test_nonexistent_commit_is_not_trusted() -> None:
    marketplace = Marketplace(
        provider=MarketplaceProvider.GITHUB,
        provider_config=GitHubMarketplaceConfig(
            owner="acme", repo="skills", ref="a" * 40
        ),
    )
    response = MagicMock(spec=requests.Response)
    response.status_code = 404
    response.headers = {}
    response.__enter__.return_value = response
    with (
        patch(
            "onyx.skills.marketplace.provider.github_authorization_header",
            return_value="Bearer test",
        ),
        patch("onyx.utils.github.ssrf_safe_get", return_value=response) as fetch,
    ):
        with pytest.raises(OnyxError, match="not found"):
            get_marketplace_adapter(marketplace, "public").fetch_if_changed()
        assert all("/commits/" in call.args[0] for call in fetch.call_args_list)
