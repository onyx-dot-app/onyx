"""Unit tests for the MCP OAuth credentials resolver and config builder.

These tests cover the fix for the "resubmit unchanged wipes client_info" bug
described in `plans/mcp-oauth-resubmit-empty-secret-fix.md`. The resolver
mirrors the LLM-provider `api_key_changed` pattern: when the frontend marks a
credential field as unchanged, the backend reuses the stored value instead of
overwriting it with whatever (likely masked) string the form replayed.
"""

import pytest
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from onyx.server.features.mcp.api import _build_oauth_admin_config_data
from onyx.server.features.mcp.api import _resolve_oauth_credentials
from onyx.server.features.mcp.models import MCPOAuthKeys
from onyx.utils.encryption import mask_string


def _make_existing_client(
    *,
    client_id: str = "stored-client-id",
    client_secret: str | None = "stored-secret",
) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uris=[AnyUrl("https://example.com/callback")],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method=("client_secret_post" if client_secret else "none"),
    )


class TestResolveOAuthCredentials:
    def test_public_client_unchanged_resubmit_keeps_stored_values(self) -> None:
        existing = _make_existing_client(client_id="abc", client_secret=None)

        resolved_id, resolved_secret = _resolve_oauth_credentials(
            request_client_id=mask_string("abc") if len("abc") >= 14 else "abc",
            request_client_id_changed=False,
            request_client_secret="",
            request_client_secret_changed=False,
            existing_client=existing,
        )

        assert resolved_id == "abc"
        assert resolved_secret is None

    def test_confidential_client_unchanged_resubmit_keeps_stored_values(self) -> None:
        stored_id = "long-client-id-123456"
        stored_secret = "long-client-secret-abcdef"
        existing = _make_existing_client(
            client_id=stored_id,
            client_secret=stored_secret,
        )

        resolved_id, resolved_secret = _resolve_oauth_credentials(
            request_client_id=mask_string(stored_id),
            request_client_id_changed=False,
            request_client_secret=mask_string(stored_secret),
            request_client_secret_changed=False,
            existing_client=existing,
        )

        assert resolved_id == stored_id
        assert resolved_secret == stored_secret

    def test_only_client_id_changed_keeps_stored_secret(self) -> None:
        existing = _make_existing_client(
            client_id="stored-id",
            client_secret="stored-secret-value",
        )

        resolved_id, resolved_secret = _resolve_oauth_credentials(
            request_client_id="brand-new-id",
            request_client_id_changed=True,
            request_client_secret=mask_string("stored-secret-value"),
            request_client_secret_changed=False,
            existing_client=existing,
        )

        assert resolved_id == "brand-new-id"
        assert resolved_secret == "stored-secret-value"

    def test_only_client_secret_changed_keeps_stored_id(self) -> None:
        existing = _make_existing_client(
            client_id="stored-client-id-1234",
            client_secret="stored-secret",
        )

        resolved_id, resolved_secret = _resolve_oauth_credentials(
            request_client_id=mask_string("stored-client-id-1234"),
            request_client_id_changed=False,
            request_client_secret="brand-new-secret",
            request_client_secret_changed=True,
            existing_client=existing,
        )

        assert resolved_id == "stored-client-id-1234"
        assert resolved_secret == "brand-new-secret"

    def test_changed_flag_with_long_masked_value_is_rejected(self) -> None:
        existing = _make_existing_client(
            client_id="real-stored-id-1234",
            client_secret="real-stored-secret-1234",
        )

        with pytest.raises(ValueError, match="oauth_client_id"):
            _resolve_oauth_credentials(
                request_client_id=mask_string("some-other-long-string"),
                request_client_id_changed=True,
                request_client_secret="anything-else",
                request_client_secret_changed=True,
                existing_client=existing,
            )

        with pytest.raises(ValueError, match="oauth_client_secret"):
            _resolve_oauth_credentials(
                request_client_id="totally-fresh-id",
                request_client_id_changed=True,
                request_client_secret=mask_string("another-long-secret"),
                request_client_secret_changed=True,
                existing_client=existing,
            )

    def test_changed_flag_with_short_mask_placeholder_is_rejected(self) -> None:
        # mask_string returns "••••••••••••" for short inputs; verify both
        # mask formats trip the safety net, not just the long form.
        short_mask = mask_string("short")
        existing = _make_existing_client()

        with pytest.raises(ValueError, match="oauth_client_secret"):
            _resolve_oauth_credentials(
                request_client_id="something",
                request_client_id_changed=True,
                request_client_secret=short_mask,
                request_client_secret_changed=True,
                existing_client=existing,
            )

    def test_no_existing_client_passes_request_values_through(self) -> None:
        # Create flow: nothing is stored yet; both flags are False (the default)
        # but there's nothing to fall back to. The resolver should resolve to
        # None for both fields, leaving the caller to handle the create path
        # explicitly (which `_upsert_mcp_server` does by only invoking the
        # resolver when an `existing_client` is present).
        resolved_id, resolved_secret = _resolve_oauth_credentials(
            request_client_id="user-typed-id",
            request_client_id_changed=False,
            request_client_secret="user-typed-secret",
            request_client_secret_changed=False,
            existing_client=None,
        )

        assert resolved_id is None
        assert resolved_secret is None

    def test_no_existing_client_with_changed_flags_uses_request_values(self) -> None:
        resolved_id, resolved_secret = _resolve_oauth_credentials(
            request_client_id="user-typed-id",
            request_client_id_changed=True,
            request_client_secret="user-typed-secret",
            request_client_secret_changed=True,
            existing_client=None,
        )

        assert resolved_id == "user-typed-id"
        assert resolved_secret == "user-typed-secret"


class TestBuildOAuthAdminConfigData:
    def test_no_client_id_returns_empty_headers_only(self) -> None:
        config_data = _build_oauth_admin_config_data(
            client_id=None,
            client_secret=None,
        )

        assert config_data == {"headers": {}}
        assert MCPOAuthKeys.CLIENT_INFO.value not in config_data

    def test_public_client_with_no_secret_still_seeds_client_info(self) -> None:
        # Regression for the original bug: a public client (id present, secret
        # absent) used to fall through the gate and silently wipe the stored
        # client_info on resubmit.
        config_data = _build_oauth_admin_config_data(
            client_id="public-client-id",
            client_secret=None,
        )

        client_info_dict = config_data.get(MCPOAuthKeys.CLIENT_INFO.value)
        assert client_info_dict is not None
        assert client_info_dict["client_id"] == "public-client-id"
        assert client_info_dict.get("client_secret") is None
        assert client_info_dict["token_endpoint_auth_method"] == "none"

    def test_confidential_client_uses_client_secret_post(self) -> None:
        config_data = _build_oauth_admin_config_data(
            client_id="confidential-id",
            client_secret="confidential-secret",
        )

        client_info_dict = config_data.get(MCPOAuthKeys.CLIENT_INFO.value)
        assert client_info_dict is not None
        assert client_info_dict["client_id"] == "confidential-id"
        assert client_info_dict["client_secret"] == "confidential-secret"
        assert client_info_dict["token_endpoint_auth_method"] == "client_secret_post"
