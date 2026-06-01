import pytest

import onyx.main as main
from onyx.configs.constants import AuthType


@pytest.fixture(autouse=True)
def _enable_redis_bearer_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "should_enable_redis_bearer_auth", lambda: True)


def test_mobile_google_oauth_requires_redirect_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "AUTH_TYPE", AuthType.CLOUD)
    monkeypatch.setattr(main, "MULTI_TENANT", False)
    monkeypatch.setattr(main, "OAUTH_ENABLED", True)
    monkeypatch.setattr(main, "MOBILE_OAUTH_REDIRECT_BASE", None)

    assert not main._should_mount_mobile_google_oauth()


def test_mobile_google_oauth_requires_oauth_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "AUTH_TYPE", AuthType.CLOUD)
    monkeypatch.setattr(main, "MULTI_TENANT", False)
    monkeypatch.setattr(main, "OAUTH_ENABLED", False)
    monkeypatch.setattr(main, "MOBILE_OAUTH_REDIRECT_BASE", "https://example.com/api")

    assert not main._should_mount_mobile_google_oauth()


def test_mobile_google_oauth_mounts_when_explicitly_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "AUTH_TYPE", AuthType.CLOUD)
    monkeypatch.setattr(main, "MULTI_TENANT", False)
    monkeypatch.setattr(main, "OAUTH_ENABLED", True)
    monkeypatch.setattr(main, "MOBILE_OAUTH_REDIRECT_BASE", "https://example.com/api")

    assert main._should_mount_mobile_google_oauth()


def test_mobile_google_oauth_requires_redis_bearer_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "should_enable_redis_bearer_auth", lambda: False)
    monkeypatch.setattr(main, "AUTH_TYPE", AuthType.CLOUD)
    monkeypatch.setattr(main, "MULTI_TENANT", False)
    monkeypatch.setattr(main, "OAUTH_ENABLED", True)
    monkeypatch.setattr(main, "MOBILE_OAUTH_REDIRECT_BASE", "https://example.com/api")

    assert not main._should_mount_mobile_google_oauth()


def test_mobile_bearer_logout_mounts_for_google_oauth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "AUTH_TYPE", AuthType.GOOGLE_OAUTH)
    monkeypatch.setattr(main, "MULTI_TENANT", False)
    monkeypatch.setattr(main, "OAUTH_ENABLED", True)
    monkeypatch.setattr(main, "MOBILE_OAUTH_REDIRECT_BASE", "https://example.com/api")

    assert main._should_mount_mobile_bearer_logout()


@pytest.mark.parametrize("auth_type", [AuthType.BASIC, AuthType.CLOUD])
def test_mobile_bearer_logout_not_duplicated_for_auth_router_modes(
    monkeypatch: pytest.MonkeyPatch,
    auth_type: AuthType,
) -> None:
    monkeypatch.setattr(main, "AUTH_TYPE", auth_type)
    monkeypatch.setattr(main, "MULTI_TENANT", False)
    monkeypatch.setattr(main, "OAUTH_ENABLED", True)
    monkeypatch.setattr(main, "MOBILE_OAUTH_REDIRECT_BASE", "https://example.com/api")

    assert not main._should_mount_mobile_bearer_logout()
