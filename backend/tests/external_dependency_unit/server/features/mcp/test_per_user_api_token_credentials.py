"""Per-user API_TOKEN MCP credentials must satisfy two invariants that
only show up in DB state, not in API responses:
`save_user_credentials` resolves `{user_email}` (and other auto
placeholders) when persisting headers, and `_upsert_mcp_server`
preserves the editing admin's stored per-user credentials when the
form flags them as unchanged. Tests poke the JSONB directly because
HTTP responses mask credential values."""

from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPTransport
from onyx.db.mcp import extract_connection_data
from onyx.db.mcp import get_user_connection_config
from onyx.db.models import User
from onyx.server.features.mcp.api import _upsert_mcp_server
from onyx.server.features.mcp.api import HEADER_SUBSTITUTIONS
from onyx.server.features.mcp.api import save_user_credentials
from onyx.server.features.mcp.models import MCPAuthTemplate
from onyx.server.features.mcp.models import MCPToolCreateRequest
from onyx.server.features.mcp.models import MCPUserCredentialsRequest
from onyx.utils.encryption import mask_string
from tests.external_dependency_unit.conftest import create_test_user


def _make_per_user_api_token_request(
    *,
    server_name: str,
    admin_credentials: dict[str, str],
    existing_server_id: int | None = None,
    description: str = "regression server",
    auth_template: MCPAuthTemplate | None = None,
    admin_credentials_changed: dict[str, bool] | None = None,
) -> MCPToolCreateRequest:
    return MCPToolCreateRequest(
        name=server_name,
        description=description,
        server_url="http://upstream.example.com/mcp",
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        transport=MCPTransport.STREAMABLE_HTTP,
        auth_template=auth_template
        or MCPAuthTemplate(
            headers={"Authorization": "PlainBasic {user_email}:{api_key}"},
            required_fields=["api_key"],
        ),
        admin_credentials=admin_credentials,
        admin_credentials_changed=admin_credentials_changed or {},
        existing_server_id=existing_server_id,
    )


def _read_user_config(*, server_id: int, user_email: str, db_session: Session) -> dict:
    """Return the unmasked JSONB blob for a user's connection config row."""
    cfg = get_user_connection_config(server_id, user_email, db_session)
    assert cfg is not None, f"no per-user config for {user_email}"
    return dict(extract_connection_data(cfg, apply_mask=False))


class TestSaveUserCredentialsSubstitutesUserEmail:
    """`save_user_credentials` must apply both user-supplied and
    auto (`{user_email}`) substitutions before persisting headers."""

    def test_user_email_in_template_resolves_at_save_time(
        self, db_session: Session
    ) -> None:
        admin = create_test_user(
            db_session, "admin_user_email_sub", role=UserRole.ADMIN
        )
        basic_user = create_test_user(db_session, "basic_user_email_sub")

        server_name = f"user-email-sub-{uuid4().hex[:8]}"
        mcp_server = _upsert_mcp_server(
            _make_per_user_api_token_request(
                server_name=server_name,
                admin_credentials={"api_key": "admin-key"},
            ),
            db_session,
            admin,
        )

        with patch(
            "onyx.server.features.mcp.api.test_mcp_server_credentials",
            return_value=(True, "ok"),
        ):
            save_user_credentials(
                MCPUserCredentialsRequest(
                    server_id=mcp_server.id,
                    credentials={"api_key": "basic-user-key"},
                    transport="streamable_http",
                ),
                db_session,
                basic_user,
            )

        cfg = _read_user_config(
            server_id=mcp_server.id,
            user_email=basic_user.email,
            db_session=db_session,
        )

        expected = f"PlainBasic {basic_user.email}:basic-user-key"
        assert cfg["headers"]["Authorization"] == expected
        assert "{user_email}" not in cfg["headers"]["Authorization"]


class TestAdminEditPreservesAdminReauth:
    """A panel save that doesn't flag credentials as changed must not
    overwrite the admin's stored per-user credentials."""

    def _create_server(
        self, db_session: Session, admin: User
    ) -> tuple[int, str, MCPAuthTemplate]:
        server_name = f"admin-edit-preserve-{uuid4().hex[:8]}"
        template = MCPAuthTemplate(
            headers={"Authorization": "PlainBasic {user_email}:{api_key}"},
            required_fields=["api_key"],
        )
        mcp_server = _upsert_mcp_server(
            _make_per_user_api_token_request(
                server_name=server_name,
                admin_credentials={"api_key": "key_A"},
                auth_template=template,
            ),
            db_session,
            admin,
        )
        return mcp_server.id, server_name, template

    def _admin_reauth(
        self, db_session: Session, admin: User, server_id: int, new_key: str
    ) -> None:
        with patch(
            "onyx.server.features.mcp.api.test_mcp_server_credentials",
            return_value=(True, "ok"),
        ):
            save_user_credentials(
                MCPUserCredentialsRequest(
                    server_id=server_id,
                    credentials={"api_key": new_key},
                    transport="streamable_http",
                ),
                db_session,
                admin,
            )

    def test_unchanged_resubmit_preserves_admins_reauthed_key(
        self, db_session: Session
    ) -> None:
        admin = create_test_user(db_session, "admin_unchanged", role=UserRole.ADMIN)
        server_id, server_name, template = self._create_server(db_session, admin)

        self._admin_reauth(db_session, admin, server_id, "key_B")

        # Panel save replays the masked original (`key_A`) with the
        # changed flag set False; `key_B` must survive.
        _upsert_mcp_server(
            _make_per_user_api_token_request(
                server_name=server_name,
                admin_credentials={"api_key": mask_string("key_A")},
                admin_credentials_changed={"api_key": False},
                existing_server_id=server_id,
                description="Updated description only",
                auth_template=template,
            ),
            db_session,
            admin,
        )

        cfg = _read_user_config(
            server_id=server_id, user_email=admin.email, db_session=db_session
        )
        assert cfg.get(HEADER_SUBSTITUTIONS) == {"api_key": "key_B"}
        assert cfg["headers"]["Authorization"] == f"PlainBasic {admin.email}:key_B"

    def test_changed_resubmit_applies_new_key(self, db_session: Session) -> None:
        admin = create_test_user(db_session, "admin_changed", role=UserRole.ADMIN)
        server_id, server_name, template = self._create_server(db_session, admin)

        self._admin_reauth(db_session, admin, server_id, "key_B")

        _upsert_mcp_server(
            _make_per_user_api_token_request(
                server_name=server_name,
                admin_credentials={"api_key": "key_C"},
                admin_credentials_changed={"api_key": True},
                existing_server_id=server_id,
                auth_template=template,
            ),
            db_session,
            admin,
        )

        cfg = _read_user_config(
            server_id=server_id, user_email=admin.email, db_session=db_session
        )
        assert cfg.get(HEADER_SUBSTITUTIONS) == {"api_key": "key_C"}
        assert cfg["headers"]["Authorization"] == f"PlainBasic {admin.email}:key_C"

    def test_other_users_per_user_config_is_never_touched(
        self, db_session: Session
    ) -> None:
        # Admin-panel cleanup must stay scoped to the editing admin.
        admin = create_test_user(
            db_session, "admin_other_unaffected", role=UserRole.ADMIN
        )
        basic_user = create_test_user(db_session, "basic_other_unaffected")
        server_id, server_name, template = self._create_server(db_session, admin)

        with patch(
            "onyx.server.features.mcp.api.test_mcp_server_credentials",
            return_value=(True, "ok"),
        ):
            save_user_credentials(
                MCPUserCredentialsRequest(
                    server_id=server_id,
                    credentials={"api_key": "user-key"},
                    transport="streamable_http",
                ),
                db_session,
                basic_user,
            )

        _upsert_mcp_server(
            _make_per_user_api_token_request(
                server_name=server_name,
                admin_credentials={"api_key": "admin-key-rotated"},
                admin_credentials_changed={"api_key": True},
                existing_server_id=server_id,
                auth_template=template,
            ),
            db_session,
            admin,
        )

        cfg = _read_user_config(
            server_id=server_id, user_email=basic_user.email, db_session=db_session
        )
        assert cfg.get(HEADER_SUBSTITUTIONS) == {"api_key": "user-key"}
        assert (
            cfg["headers"]["Authorization"] == f"PlainBasic {basic_user.email}:user-key"
        )
