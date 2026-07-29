"""Editing MCP credentials must persist the new values.

Regression coverage for a customer report: changing the API key of an
existing server and hitting Connect silently kept the old key. Change
detection must be value-based — clients that predate the `*_changed`
flags (older frontends, cached bundles after an upgrade, scripts) send
only the new value — and the per-user modal's masked replays of
untouched fields must never be persisted as literal credentials.
Replays the exact payloads the frontend sends and inspects DB state
directly because API responses mask credential values."""

from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.mcp import extract_connection_data, get_user_connection_config
from onyx.db.models import MCPServer as DbMCPServer
from onyx.server.features.mcp.api import (
    HEADER_SUBSTITUTIONS,
    _upsert_mcp_server,
    save_user_credentials,
)
from onyx.server.features.mcp.models import (
    MCPAuthTemplate,
    MCPToolCreateRequest,
    MCPUserCredentialsRequest,
)
from onyx.utils.encryption import mask_string
from tests.external_dependency_unit.conftest import create_test_user


def _shared_token_request(
    *,
    server_name: str,
    api_token: str | None,
    api_token_changed: bool,
    existing_server_id: int | None = None,
    auth_template: MCPAuthTemplate | None = None,
) -> MCPToolCreateRequest:
    """Mirror MCPAuthenticationModal.constructServerData for the admin
    shared-key tab."""
    return MCPToolCreateRequest(
        name=server_name,
        description="credential edit persistence",
        server_url="http://upstream.example.com/mcp",
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
        transport=MCPTransport.STREAMABLE_HTTP,
        api_token=api_token,
        api_token_changed=api_token_changed,
        auth_template=auth_template,
        existing_server_id=existing_server_id,
    )


def _read_admin_config(db_session: Session, server_id: int) -> dict:
    # A fresh API request reads with a fresh session; drop identity-map state
    # so the assertion sees committed rows, not this session's cached objects.
    db_session.expire_all()
    server = db_session.get(DbMCPServer, server_id)
    assert server is not None and server.admin_connection_config is not None
    return dict(
        extract_connection_data(server.admin_connection_config, apply_mask=False)
    )


class TestAdminSharedTokenEdit:
    def test_change_api_key_with_changed_flag(self, db_session: Session) -> None:
        """Exact current-frontend payload: new token + api_token_changed=True."""
        admin = create_test_user(db_session, "admin_shared_edit", role=UserRole.ADMIN)
        name = f"shared-edit-{uuid4().hex[:8]}"

        server = _upsert_mcp_server(
            _shared_token_request(
                server_name=name,
                api_token="OLDKEY-aaaa-bbbb-cccc-1111",
                api_token_changed=True,
            ),
            db_session,
            admin,
        )
        assert (
            _read_admin_config(db_session, server.id)["api_token"]
            == "OLDKEY-aaaa-bbbb-cccc-1111"
        )

        # Edit: user pastes a new key; frontend computes changed=True.
        _upsert_mcp_server(
            _shared_token_request(
                server_name=name,
                api_token="NEWKEY-dddd-eeee-ffff-2222",
                api_token_changed=True,
                existing_server_id=server.id,
            ),
            db_session,
            admin,
        )
        cfg = _read_admin_config(db_session, server.id)
        assert cfg["api_token"] == "NEWKEY-dddd-eeee-ffff-2222", cfg
        assert cfg["headers"]["Authorization"] == "Bearer NEWKEY-dddd-eeee-ffff-2222"

    def test_change_api_key_without_changed_flag_old_client(
        self, db_session: Session
    ) -> None:
        """Older frontend (pre-changed-flag): sends the new real token with no
        flag. `_resolve_shared_api_token` should still take the real token."""
        admin = create_test_user(db_session, "admin_shared_oldfe", role=UserRole.ADMIN)
        name = f"shared-oldfe-{uuid4().hex[:8]}"

        server = _upsert_mcp_server(
            _shared_token_request(
                server_name=name,
                api_token="OLDKEY-aaaa-bbbb-cccc-1111",
                api_token_changed=True,
            ),
            db_session,
            admin,
        )

        _upsert_mcp_server(
            _shared_token_request(
                server_name=name,
                api_token="NEWKEY-dddd-eeee-ffff-2222",
                api_token_changed=False,
                existing_server_id=server.id,
            ),
            db_session,
            admin,
        )
        cfg = _read_admin_config(db_session, server.id)
        assert cfg["api_token"] == "NEWKEY-dddd-eeee-ffff-2222", cfg

    def test_masked_replay_with_no_edit_preserves_token(
        self, db_session: Session
    ) -> None:
        """Reopening the modal and hitting Connect without editing replays the
        masked token with changed=False; the stored token must survive."""
        admin = create_test_user(db_session, "admin_shared_noop", role=UserRole.ADMIN)
        name = f"shared-noop-{uuid4().hex[:8]}"

        server = _upsert_mcp_server(
            _shared_token_request(
                server_name=name,
                api_token="OLDKEY-aaaa-bbbb-cccc-1111",
                api_token_changed=True,
            ),
            db_session,
            admin,
        )

        _upsert_mcp_server(
            _shared_token_request(
                server_name=name,
                api_token=mask_string("OLDKEY-aaaa-bbbb-cccc-1111"),
                api_token_changed=False,
                existing_server_id=server.id,
            ),
            db_session,
            admin,
        )
        cfg = _read_admin_config(db_session, server.id)
        assert cfg["api_token"] == "OLDKEY-aaaa-bbbb-cccc-1111", cfg


class TestEndUserCredentialUpdate:
    def _make_per_user_server(self, db_session: Session, admin) -> int:
        req = MCPToolCreateRequest(
            name=f"per-user-update-{uuid4().hex[:8]}",
            description="credential edit persistence",
            server_url="http://upstream.example.com/mcp",
            auth_type=MCPAuthenticationType.API_TOKEN,
            auth_performer=MCPAuthenticationPerformer.PER_USER,
            transport=MCPTransport.STREAMABLE_HTTP,
            auth_template=MCPAuthTemplate(
                headers={"Authorization": "Bearer {api_key}"},
                required_fields=["api_key"],
            ),
            admin_credentials={"api_key": "admin-seed-key"},
            admin_credentials_changed={"api_key": True},
        )
        return _upsert_mcp_server(req, db_session, admin).id

    def test_user_updates_their_api_key(self, db_session: Session) -> None:
        """End user connects with key A then updates to key B via the
        user-credentials modal. Key B must be stored."""
        admin = create_test_user(db_session, "admin_enduser_upd", role=UserRole.ADMIN)
        user = create_test_user(db_session, "basic_enduser_upd")
        server_id = self._make_per_user_server(db_session, admin)

        with patch(
            "onyx.server.features.mcp.api.test_mcp_server_credentials",
            return_value=(True, "ok"),
        ):
            save_user_credentials(
                MCPUserCredentialsRequest(
                    server_id=server_id,
                    credentials={"api_key": "USER-KEY-A-0000-1111"},
                    transport="streamable_http",
                ),
                db_session,
                user,
            )
            save_user_credentials(
                MCPUserCredentialsRequest(
                    server_id=server_id,
                    credentials={"api_key": "USER-KEY-B-2222-3333"},
                    transport="streamable_http",
                ),
                db_session,
                user,
            )

        db_session.expire_all()
        cfg_row = get_user_connection_config(server_id, user.email, db_session)
        assert cfg_row is not None
        cfg = dict(extract_connection_data(cfg_row, apply_mask=False))
        assert cfg.get(HEADER_SUBSTITUTIONS) == {"api_key": "USER-KEY-B-2222-3333"}, cfg
        assert cfg["headers"]["Authorization"] == "Bearer USER-KEY-B-2222-3333"

    def test_user_replays_masked_value_for_untouched_field(
        self, db_session: Session
    ) -> None:
        """Multi-field template: the modal seeds inputs with MASKED existing
        values; the user edits only one field and the other is submitted as the
        masked literal. The stored value for the untouched field must not be
        clobbered with the mask."""
        admin = create_test_user(db_session, "admin_masked_replay", role=UserRole.ADMIN)
        user = create_test_user(db_session, "basic_masked_replay")

        req = MCPToolCreateRequest(
            name=f"masked-replay-{uuid4().hex[:8]}",
            description="credential edit persistence",
            server_url="http://upstream.example.com/mcp",
            auth_type=MCPAuthenticationType.API_TOKEN,
            auth_performer=MCPAuthenticationPerformer.PER_USER,
            transport=MCPTransport.STREAMABLE_HTTP,
            auth_template=MCPAuthTemplate(
                headers={
                    "Authorization": "Bearer {api_key}",
                    "X-Org": "{org_id}",
                },
                required_fields=["api_key", "org_id"],
            ),
            admin_credentials={"api_key": "seed", "org_id": "seed-org"},
            admin_credentials_changed={"api_key": True, "org_id": True},
        )
        server_id = _upsert_mcp_server(req, db_session, admin).id

        with patch(
            "onyx.server.features.mcp.api.test_mcp_server_credentials",
            return_value=(True, "ok"),
        ):
            save_user_credentials(
                MCPUserCredentialsRequest(
                    server_id=server_id,
                    credentials={
                        "api_key": "USER-KEY-A-0000-1111",
                        "org_id": "org-12345-abcdef",
                    },
                    transport="streamable_http",
                ),
                db_session,
                user,
            )
            # Modal replay: api_key edited, org_id left as the masked seed.
            save_user_credentials(
                MCPUserCredentialsRequest(
                    server_id=server_id,
                    credentials={
                        "api_key": "USER-KEY-B-2222-3333",
                        "org_id": mask_string("org-12345-abcdef"),
                    },
                    transport="streamable_http",
                ),
                db_session,
                user,
            )

        db_session.expire_all()
        cfg_row = get_user_connection_config(server_id, user.email, db_session)
        assert cfg_row is not None
        cfg = dict(extract_connection_data(cfg_row, apply_mask=False))
        assert cfg["headers"]["X-Org"] == "org-12345-abcdef", cfg
        assert cfg["headers"]["Authorization"] == "Bearer USER-KEY-B-2222-3333", cfg


class TestFlaglessClientsPerUserAndOAuth:
    """Clients that predate the `*_changed` flags send only the edited
    values; a real (unmasked) differing value must still win."""

    def test_per_user_admin_credentials_without_flags(
        self, db_session: Session
    ) -> None:
        admin = create_test_user(db_session, "admin_flagless", role=UserRole.ADMIN)
        name = f"flagless-{uuid4().hex[:8]}"
        template = MCPAuthTemplate(
            headers={"Authorization": "Bearer {api_key}"},
            required_fields=["api_key"],
        )

        def mk(
            credentials: dict[str, str], existing: int | None
        ) -> MCPToolCreateRequest:
            return MCPToolCreateRequest(
                name=name,
                description="credential edit persistence",
                server_url="http://upstream.example.com/mcp",
                auth_type=MCPAuthenticationType.API_TOKEN,
                auth_performer=MCPAuthenticationPerformer.PER_USER,
                transport=MCPTransport.STREAMABLE_HTTP,
                auth_template=template,
                admin_credentials=credentials,
                admin_credentials_changed={},  # old client: no flags
                existing_server_id=existing,
            )

        server = _upsert_mcp_server(
            mk({"api_key": "ADMIN-KEY-A-0000-1111"}, None), db_session, admin
        )
        _upsert_mcp_server(
            mk({"api_key": "ADMIN-KEY-B-2222-3333"}, server.id), db_session, admin
        )

        db_session.expire_all()
        cfg_row = get_user_connection_config(server.id, admin.email, db_session)
        assert cfg_row is not None
        cfg = dict(extract_connection_data(cfg_row, apply_mask=False))
        assert cfg.get(HEADER_SUBSTITUTIONS) == {"api_key": "ADMIN-KEY-B-2222-3333"}

    def test_per_user_masked_replay_without_flags_preserved(
        self, db_session: Session
    ) -> None:
        admin = create_test_user(db_session, "admin_flagless_mask", role=UserRole.ADMIN)
        name = f"flagless-mask-{uuid4().hex[:8]}"
        template = MCPAuthTemplate(
            headers={"Authorization": "Bearer {api_key}"},
            required_fields=["api_key"],
        )

        def mk(
            credentials: dict[str, str], existing: int | None
        ) -> MCPToolCreateRequest:
            return MCPToolCreateRequest(
                name=name,
                description="credential edit persistence",
                server_url="http://upstream.example.com/mcp",
                auth_type=MCPAuthenticationType.API_TOKEN,
                auth_performer=MCPAuthenticationPerformer.PER_USER,
                transport=MCPTransport.STREAMABLE_HTTP,
                auth_template=template,
                admin_credentials=credentials,
                admin_credentials_changed={},
                existing_server_id=existing,
            )

        server = _upsert_mcp_server(
            mk({"api_key": "ADMIN-KEY-A-0000-1111"}, None), db_session, admin
        )
        _upsert_mcp_server(
            mk({"api_key": mask_string("ADMIN-KEY-A-0000-1111")}, server.id),
            db_session,
            admin,
        )

        db_session.expire_all()
        cfg_row = get_user_connection_config(server.id, admin.email, db_session)
        assert cfg_row is not None
        cfg = dict(extract_connection_data(cfg_row, apply_mask=False))
        assert cfg.get(HEADER_SUBSTITUTIONS) == {"api_key": "ADMIN-KEY-A-0000-1111"}

    def test_oauth_resolver_flagless_real_value_wins(self) -> None:
        from mcp.shared.auth import OAuthClientInformationFull
        from pydantic import AnyUrl

        from onyx.server.features.mcp.api import _resolve_oauth_credentials

        existing = OAuthClientInformationFull(
            client_id="stored-client-id-0000",
            client_secret="stored-secret-1111",
            redirect_uris=[AnyUrl("https://onyx.example.com/mcp/oauth/callback")],
        )

        # Old client edits the secret: real value, no flags.
        resolved_id, resolved_secret = _resolve_oauth_credentials(
            request_client_id=mask_string("stored-client-id-0000"),
            request_client_id_changed=False,
            request_client_secret="edited-secret-2222",
            request_client_secret_changed=False,
            existing_client=existing,
        )
        assert resolved_id == "stored-client-id-0000"
        assert resolved_secret == "edited-secret-2222"

        # Pure masked replay keeps storage.
        resolved_id, resolved_secret = _resolve_oauth_credentials(
            request_client_id=mask_string("stored-client-id-0000"),
            request_client_id_changed=False,
            request_client_secret=mask_string("stored-secret-1111"),
            request_client_secret_changed=False,
            existing_client=existing,
        )
        assert resolved_id == "stored-client-id-0000"
        assert resolved_secret == "stored-secret-1111"
