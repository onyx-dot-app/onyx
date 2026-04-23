"""Unit tests for the MCP OAuth credentials resolver and config builder.

These tests cover the fix for the "resubmit unchanged wipes client_info" bug
described in `plans/mcp-oauth-resubmit-empty-secret-fix.md`. The resolver
mirrors the LLM-provider `api_key_changed` pattern: when the frontend marks a
credential field as unchanged, the backend reuses the stored value instead of
overwriting it with whatever (likely masked) string the form replayed.
"""

from typing import Literal

import pytest
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from onyx.server.features.mcp.api import _build_oauth_admin_config_data
from onyx.server.features.mcp.api import _build_oauth_admin_config_data_for_update
from onyx.server.features.mcp.api import _resolve_oauth_credentials
from onyx.server.features.mcp.models import MCPOAuthKeys
from onyx.utils.encryption import mask_string

TokenEndpointAuthMethod = Literal[
    "none", "client_secret_post", "client_secret_basic", "private_key_jwt"
]


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


def _make_dcr_registered_client(
    *,
    client_id: str = "dcr-client-id",
    client_secret: str | None = "dcr-client-secret",
    token_endpoint_auth_method: TokenEndpointAuthMethod = "client_secret_basic",
) -> OAuthClientInformationFull:
    """Build a client_info that looks like a real DCR response — with the
    provider-managed fields the merge helper is responsible for preserving.

    NOTE: the MCP SDK's `OAuthClientInformationFull` only models a subset of
    the DCR response (RFC 7591). RFC 7592 fields like `registration_access_token`
    and `registration_client_uri` are not on the model and are silently
    dropped at validate time. The merge helper can therefore only preserve
    fields that the SDK actually models — primarily `client_id_issued_at`,
    `client_secret_expires_at`, the negotiated `token_endpoint_auth_method`,
    and metadata like `client_name`.
    """
    return OAuthClientInformationFull(
        client_id=client_id,
        client_secret=client_secret,
        client_id_issued_at=1_700_000_000,
        client_secret_expires_at=1_900_000_000,
        client_name="DCR Registered Client",
        redirect_uris=[AnyUrl("https://idp.example.com/legacy-callback")],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method=token_endpoint_auth_method,
        scope="openid profile",
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
        # Nothing stored yet but the form replayed defaults (both *_changed False).
        # `_connect_oauth` always runs the resolver; we must keep the submitted
        # credentials so OAuth config is not rebuilt empty after upsert.
        resolved_id, resolved_secret = _resolve_oauth_credentials(
            request_client_id="user-typed-id",
            request_client_id_changed=False,
            request_client_secret="user-typed-secret",
            request_client_secret_changed=False,
            existing_client=None,
        )

        assert resolved_id == "user-typed-id"
        assert resolved_secret == "user-typed-secret"

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


class TestBuildOAuthAdminConfigDataForUpdate:
    """Tests for the merge variant that preserves provider-managed fields
    (`client_id_issued_at`, `client_secret_expires_at`,
    `token_endpoint_auth_method`, etc.) when re-saving OAuth config.

    See `plans/mcp-oauth-resubmit-preserve-client-info.md`.
    """

    def test_only_client_secret_changed_preserves_dcr_metadata(self) -> None:
        existing = _make_dcr_registered_client(
            client_id="dcr-id",
            client_secret="old-secret",
            token_endpoint_auth_method="client_secret_basic",
        )

        config_data = _build_oauth_admin_config_data_for_update(
            client_id="dcr-id",
            client_secret="new-secret",
            existing_client=existing,
        )

        client_info_dict = config_data.get(MCPOAuthKeys.CLIENT_INFO.value)
        assert client_info_dict is not None
        # admin-managed fields reflect the update
        assert client_info_dict["client_id"] == "dcr-id"
        assert client_info_dict["client_secret"] == "new-secret"
        # provider-managed fields are preserved
        assert client_info_dict["client_id_issued_at"] == 1_700_000_000
        assert client_info_dict["client_secret_expires_at"] == 1_900_000_000
        assert client_info_dict["token_endpoint_auth_method"] == "client_secret_basic"
        assert client_info_dict["client_name"] == "DCR Registered Client"

    def test_client_id_changed_discards_dcr_metadata(self) -> None:
        existing = _make_dcr_registered_client(
            client_id="old-dcr-id",
            client_secret="old-secret",
            token_endpoint_auth_method="client_secret_basic",
        )

        config_data = _build_oauth_admin_config_data_for_update(
            client_id="brand-new-id",
            client_secret="brand-new-secret",
            existing_client=existing,
        )

        client_info_dict = config_data.get(MCPOAuthKeys.CLIENT_INFO.value)
        assert client_info_dict is not None
        assert client_info_dict["client_id"] == "brand-new-id"
        assert client_info_dict["client_secret"] == "brand-new-secret"
        # DCR metadata tied to the OLD client_id is stale; we should start
        # fresh from the template.
        assert client_info_dict.get("client_id_issued_at") is None
        assert client_info_dict.get("client_secret_expires_at") is None
        assert client_info_dict.get("client_name") is None
        # Template path negotiates auth method based on secret presence.
        assert client_info_dict["token_endpoint_auth_method"] == "client_secret_post"

    def test_existing_without_dcr_metadata_resubmit_succeeds(self) -> None:
        # Manually-entered confidential client with no provider-managed
        # fields to preserve: the merge path should still cleanly update
        # the secret without erroring out.
        existing = _make_existing_client(
            client_id="manual-id",
            client_secret="old-secret",
        )

        config_data = _build_oauth_admin_config_data_for_update(
            client_id="manual-id",
            client_secret="new-secret",
            existing_client=existing,
        )

        client_info_dict = config_data.get(MCPOAuthKeys.CLIENT_INFO.value)
        assert client_info_dict is not None
        assert client_info_dict["client_id"] == "manual-id"
        assert client_info_dict["client_secret"] == "new-secret"
        assert client_info_dict["token_endpoint_auth_method"] == "client_secret_post"
        assert client_info_dict.get("client_id_issued_at") is None

    def test_no_client_id_returns_empty_config(self) -> None:
        # A resubmit that clears the client_id (e.g., admin wants to fall
        # back to DCR) collapses to the template's empty-config behavior
        # rather than carrying the merged dict forward with a None id.
        existing = _make_dcr_registered_client(client_id="dcr-id")

        config_data = _build_oauth_admin_config_data_for_update(
            client_id=None,
            client_secret=None,
            existing_client=existing,
        )

        assert config_data == {"headers": {}}
        assert MCPOAuthKeys.CLIENT_INFO.value not in config_data

    def test_public_to_confidential_keeps_negotiated_auth_method(self) -> None:
        # Existing registration was negotiated as a public client
        # (token_endpoint_auth_method="none"). Admin types a brand-new
        # secret without changing the client_id. The provider-negotiated
        # auth method is preserved verbatim — admin must explicitly
        # re-register the client with the IdP to switch flows.
        existing = _make_dcr_registered_client(
            client_id="public-id",
            client_secret=None,
            token_endpoint_auth_method="none",
        )

        config_data = _build_oauth_admin_config_data_for_update(
            client_id="public-id",
            client_secret="newly-typed-secret",
            existing_client=existing,
        )

        client_info_dict = config_data.get(MCPOAuthKeys.CLIENT_INFO.value)
        assert client_info_dict is not None
        assert client_info_dict["client_id"] == "public-id"
        assert client_info_dict["client_secret"] == "newly-typed-secret"
        assert client_info_dict["token_endpoint_auth_method"] == "none"

    def test_stale_none_auth_method_is_healed_from_secret_presence(self) -> None:
        # Before the helper enforced `token_endpoint_auth_method`, records
        # could be persisted with it as None. The SDK silently omits the
        # client secret on token exchange in that case, which manifests as
        # `invalid_client` from the IdP. The merge path heals these records
        # by deriving the method from the resolved client_secret.
        existing = OAuthClientInformationFull(
            client_id="legacy-id",
            client_secret="legacy-secret",
            redirect_uris=[AnyUrl("https://example.com/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method=None,
        )

        config_data = _build_oauth_admin_config_data_for_update(
            client_id="legacy-id",
            client_secret="legacy-secret",
            existing_client=existing,
        )

        client_info_dict = config_data.get(MCPOAuthKeys.CLIENT_INFO.value)
        assert client_info_dict is not None
        assert client_info_dict["token_endpoint_auth_method"] == "client_secret_post"

    def test_redirect_uris_and_scope_are_refreshed_from_defaults(self) -> None:
        # The admin-managed fields (redirect_uris, scope) should always be
        # rewritten from our deployment config, not preserved from the
        # stored value — otherwise we'd be stuck with whatever a
        # mis-deployed callback URL was originally registered as.
        existing = _make_dcr_registered_client(client_id="dcr-id")

        config_data = _build_oauth_admin_config_data_for_update(
            client_id="dcr-id",
            client_secret="new-secret",
            existing_client=existing,
        )

        client_info_dict = config_data.get(MCPOAuthKeys.CLIENT_INFO.value)
        assert client_info_dict is not None
        # redirect_uris was overwritten from our WEB_DOMAIN-derived default
        assert client_info_dict["redirect_uris"] != [
            "https://idp.example.com/legacy-callback"
        ]
        assert any(
            "/mcp/oauth/callback" in str(u) for u in client_info_dict["redirect_uris"]
        )
        # scope is reset to REQUESTED_SCOPE (currently None)
        assert client_info_dict.get("scope") is None
