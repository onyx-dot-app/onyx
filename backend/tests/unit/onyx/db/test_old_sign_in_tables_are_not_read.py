"""The integration tables replaced the old sign-in columns and tables. They
stay for a rollback; runtime code must not read them."""

import re
from pathlib import Path

import pytest
from sqlalchemy.orm import class_mapper

from onyx.db.models import ExternalApp, MCPServer

_BACKEND = Path(__file__).resolve().parents[4]

_OLD_COLUMNS = [
    (MCPServer, "auth_type"),
    (MCPServer, "auth_performer"),
    (MCPServer, "oauth_provider_mode"),
    (MCPServer, "oauth_authorization_endpoint"),
    (MCPServer, "oauth_token_endpoint"),
    (MCPServer, "oauth_scopes_override"),
    (MCPServer, "oauth_additional_auth_params"),
    (MCPServer, "oauth_cimd_enabled"),
    (MCPServer, "admin_connection_config_id"),
    (ExternalApp, "organization_credentials"),
]

# Old tables with no runtime reader. The model file and comments may name them.
_OLD_TABLES = re.compile(
    r"\b(external_app__skill|external_app_user_credential|mcp_connection_config"
    r"|MCPConnectionConfig)\b"
)


@pytest.mark.parametrize(("model", "column"), _OLD_COLUMNS)
def test_an_old_sign_in_column_raises_when_read(model: type, column: str) -> None:
    prop = class_mapper(model).column_attrs[column]
    assert prop.deferred
    assert prop.strategy_key == (
        ("deferred", True),
        ("instrument", True),
        ("raiseload", True),
    )


def test_no_runtime_code_names_an_old_sign_in_table() -> None:
    found = [
        f"{path.relative_to(_BACKEND)}:{number}"
        for root in ("onyx", "ee")
        for path in (_BACKEND / root).rglob("*.py")
        if path != _BACKEND / "onyx/db/models.py"
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if _OLD_TABLES.search(line.split("#", 1)[0])
    ]
    assert found == []
