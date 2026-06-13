"""`_build_headers_from_template` is the single source of truth for
rendering per-user API_TOKEN headers: it must apply both user-supplied
substitutions and auto ones (e.g. `{user_email}`) in one pass."""

from onyx.server.features.mcp.api import _build_headers_from_template
from onyx.server.features.mcp.models import MCPAuthTemplate


class TestBuildHeadersFromTemplate:
    def test_user_email_placeholder_alone_is_substituted(self) -> None:
        template = MCPAuthTemplate(
            headers={"X-User": "{user_email}"},
            required_fields=[],
        )
        headers = _build_headers_from_template(
            template_data=template,
            credentials={},
            user_email="alice@example.com",
        )
        assert headers == {"X-User": "alice@example.com"}

    def test_user_email_and_user_supplied_key_substituted_together(self) -> None:
        # Both placeholder classes must resolve in a single pass.
        template = MCPAuthTemplate(
            headers={"Authorization": "PlainBasic {user_email}:{api_key}"},
            required_fields=["api_key"],
        )
        headers = _build_headers_from_template(
            template_data=template,
            credentials={"api_key": "ATATT-secret"},
            user_email="anuj@hudson-trading.com",
        )
        assert headers == {
            "Authorization": "PlainBasic anuj@hudson-trading.com:ATATT-secret"
        }

    def test_user_supplied_key_alone_is_substituted(self) -> None:
        template = MCPAuthTemplate(
            headers={"Authorization": "Bearer {api_key}"},
            required_fields=["api_key"],
        )
        headers = _build_headers_from_template(
            template_data=template,
            credentials={"api_key": "k"},
            user_email="ignored@example.com",
        )
        assert headers == {"Authorization": "Bearer k"}

    def test_empty_header_name_is_dropped(self) -> None:
        # Empty header names must be filtered (otherwise HTTP layer breaks).
        template = MCPAuthTemplate(
            headers={"": "Bearer {api_key}", "Authorization": "Bearer {api_key}"},
            required_fields=["api_key"],
        )
        headers = _build_headers_from_template(
            template_data=template,
            credentials={"api_key": "k"},
            user_email="alice@example.com",
        )
        assert headers == {"Authorization": "Bearer k"}
