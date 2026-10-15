"""Unit coverage for `generate_password`: the password it returns must pass
`UserManager.validate_password` under the configured password policy (length
bounds and every require_* flag), since admin reset and JWT provisioning save it
through that check."""

from unittest.mock import MagicMock

import pytest

from onyx.auth import users as users_module
from onyx.auth.users import UserManager, generate_password
from onyx.configs.constants import PASSWORD_SPECIAL_CHARS
from onyx.server.security.models import SecuritySettings
from onyx.server.security.store import _build_env_defaults

# Generated passwords are random, so each policy is checked over many samples.
_SAMPLES = 200
_ALL_REQUIRED = {
    "password_require_uppercase": True,
    "password_require_lowercase": True,
    "password_require_digit": True,
    "password_require_special_char": True,
}


def _policy(**overrides: object) -> SecuritySettings:
    return _build_env_defaults().model_copy(
        update={
            "password_min_length": 8,
            "password_max_length": 64,
            **overrides,
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({}, id="default"),
        pytest.param({"password_min_length": 20}, id="min_20"),
        pytest.param(
            {"password_min_length": 20, "password_max_length": 20}, id="exactly_20"
        ),
        pytest.param({"password_min_length": 4, "password_max_length": 4}, id="max_4"),
        pytest.param({"password_min_length": 20, **_ALL_REQUIRED}, id="min_20_all"),
        pytest.param(
            {"password_min_length": 0, "password_max_length": 4, **_ALL_REQUIRED},
            id="max_4_all",
        ),
    ],
)
async def test_generated_password_passes_policy(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, object]
) -> None:
    settings = _policy(**overrides)
    monkeypatch.setattr(users_module, "get_security_settings", lambda: settings)
    user_manager = UserManager(MagicMock())

    for _ in range(_SAMPLES):
        password = generate_password()
        assert (
            settings.password_min_length
            <= len(password)
            <= settings.password_max_length
        )
        await user_manager.validate_password(password, MagicMock())


def test_generated_password_keeps_default_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _policy()
    monkeypatch.setattr(users_module, "get_security_settings", lambda: settings)
    assert len(generate_password()) == 12


def test_generated_password_uses_only_accepted_special_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _policy(password_min_length=64)
    monkeypatch.setattr(users_module, "get_security_settings", lambda: settings)
    allowed = set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        + PASSWORD_SPECIAL_CHARS
    )
    for _ in range(_SAMPLES):
        assert set(generate_password()) <= allowed
