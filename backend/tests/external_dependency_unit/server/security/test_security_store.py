import pytest

from onyx.configs.constants import KV_SECURITY_SETTINGS_KEY
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.security.models import SecuritySettings
from onyx.server.security.store import load_raw_security_settings
from onyx.server.security.store import load_security_settings
from onyx.server.security.store import store_security_settings


@pytest.fixture(autouse=True)
def _clear_kv(tenant_context: None) -> None:  # noqa: ARG001
    """Ensure each test starts with no stored SecuritySettings."""
    try:
        get_kv_store().delete(KV_SECURITY_SETTINGS_KEY)
    except KvKeyNotFoundError:
        pass


def test_raw_load_with_no_stored_value_returns_empty() -> None:
    raw = load_raw_security_settings()
    assert raw == SecuritySettings()
    # No env fallbacks have been applied — every field is None.
    assert raw.user_directory_admin_only is None
    assert raw.password_min_length is None


def test_load_with_no_stored_value_uses_env_fallbacks() -> None:
    settings = load_security_settings()
    # Env fallbacks fill in every field — none should be None.
    assert settings.user_directory_admin_only is not None
    assert settings.track_external_idp_expiry is not None
    assert settings.require_email_verification is not None
    assert settings.mask_credential_prefix is not None
    assert settings.valid_email_domains is not None
    assert settings.password_min_length is not None
    assert settings.password_max_length is not None
    assert settings.password_require_uppercase is not None
    assert settings.password_require_lowercase is not None
    assert settings.password_require_digit is not None
    assert settings.password_require_special_char is not None


def test_stored_value_wins_over_env_fallback() -> None:
    store_security_settings(
        SecuritySettings(
            user_directory_admin_only=True,
            password_min_length=42,
            valid_email_domains=["onyx.app", "example.com"],
        )
    )

    settings = load_security_settings()
    assert settings.user_directory_admin_only is True
    assert settings.password_min_length == 42
    assert settings.valid_email_domains == ["onyx.app", "example.com"]


def test_partial_store_leaves_unset_fields_on_env_fallback() -> None:
    store_security_settings(SecuritySettings(password_min_length=99))

    raw = load_raw_security_settings()
    assert raw.password_min_length == 99
    assert raw.user_directory_admin_only is None

    settings = load_security_settings()
    # Stored value wins for the one set field.
    assert settings.password_min_length == 99
    # Env fallback fills in the rest.
    assert settings.user_directory_admin_only is not None
