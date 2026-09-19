"""`_resolve_admin_credentials` is the per-key "changed flag + mask
rejector" used when persisting `admin_credentials` for a per-user
API_TOKEN MCP server. Mirrors `_resolve_oauth_credentials` (covered
in `test_oauth_credentials_resolver.py`)."""

import pytest

from onyx.server.features.mcp.api import _resolve_admin_credentials
from onyx.utils.encryption import mask_string


class TestResolveAdminCredentials:
    def test_unchanged_resubmit_with_masked_values_keeps_stored(self) -> None:
        # Each unchanged field → stored value, never the replayed mask.
        stored = {
            "api_key": "long-api-key-secret-1234",
            "username": "stored-username-1234",
        }
        request = {
            "api_key": mask_string("long-api-key-secret-1234"),
            "username": mask_string("stored-username-1234"),
        }
        changed: dict[str, bool] = {"api_key": False, "username": False}

        resolved = _resolve_admin_credentials(
            request_credentials=request,
            request_credentials_changed=changed,
            existing_user_credentials=stored,
        )

        assert resolved == stored

    def test_partial_change_keeps_unflagged_fields(self) -> None:
        stored = {"api_key": "stored-key-1234", "username": "stored-user-1234"}
        request = {
            "api_key": "brand-new-key",
            "username": mask_string("stored-user-1234"),
        }
        changed = {"api_key": True, "username": False}

        resolved = _resolve_admin_credentials(
            request_credentials=request,
            request_credentials_changed=changed,
            existing_user_credentials=stored,
        )

        assert resolved == {
            "api_key": "brand-new-key",
            "username": "stored-user-1234",
        }

    def test_missing_changed_flag_defaults_to_false(self) -> None:
        # Older clients omit the flag; treat as unchanged.
        stored = {"api_key": "stored-key-1234"}
        request = {"api_key": mask_string("stored-key-1234")}

        resolved = _resolve_admin_credentials(
            request_credentials=request,
            request_credentials_changed={},
            existing_user_credentials=stored,
        )

        assert resolved == stored

    def test_changed_flag_with_long_mask_is_rejected(self) -> None:
        stored = {"api_key": "stored-key-1234"}
        request = {"api_key": mask_string("some-other-long-string")}
        changed = {"api_key": True}

        with pytest.raises(ValueError, match="api_key"):
            _resolve_admin_credentials(
                request_credentials=request,
                request_credentials_changed=changed,
                existing_user_credentials=stored,
            )

    def test_changed_flag_with_short_mask_placeholder_is_rejected(self) -> None:
        # `mask_string` uses a bullet-string placeholder for short inputs.
        stored = {"api_key": "stored-key-1234"}
        request = {"api_key": mask_string("short")}
        changed = {"api_key": True}

        with pytest.raises(ValueError, match="api_key"):
            _resolve_admin_credentials(
                request_credentials=request,
                request_credentials_changed=changed,
                existing_user_credentials=stored,
            )

    def test_no_stored_creds_passes_request_values_through(self) -> None:
        # New-server-create path: no stored fallback available.
        request = {"api_key": "user-typed-key", "username": "user-typed-user"}

        resolved = _resolve_admin_credentials(
            request_credentials=request,
            request_credentials_changed={},
            existing_user_credentials=None,
        )

        assert resolved == request

    def test_no_stored_creds_with_changed_flags_uses_request_values(self) -> None:
        request = {"api_key": "user-typed-key"}
        changed = {"api_key": True}

        resolved = _resolve_admin_credentials(
            request_credentials=request,
            request_credentials_changed=changed,
            existing_user_credentials=None,
        )

        assert resolved == request

    def test_empty_request_returns_empty(self) -> None:
        resolved = _resolve_admin_credentials(
            request_credentials={},
            request_credentials_changed={},
            existing_user_credentials={"api_key": "stored"},
        )
        assert resolved == {}

    def test_request_key_not_in_stored_passes_through(self) -> None:
        # New template field with no stored fallback; take the request value.
        stored = {"api_key": "stored-key-1234"}
        request = {
            "api_key": mask_string("stored-key-1234"),
            "username": "new-required-field-value",
        }
        changed = {"api_key": False, "username": False}

        resolved = _resolve_admin_credentials(
            request_credentials=request,
            request_credentials_changed=changed,
            existing_user_credentials=stored,
        )

        assert resolved == {
            "api_key": "stored-key-1234",
            "username": "new-required-field-value",
        }
