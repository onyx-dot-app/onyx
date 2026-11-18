"""Passthrough sign-in of a custom tool keeps its static header values."""

from onyx.integrations.connection_models import ConnectionSecret
from onyx.integrations.connections import render_headers
from onyx.server.features.tool.api import _auth_settings
from onyx.server.features.tool.models import Header


def test_passthrough_static_headers_render_as_entered() -> None:
    settings = _auth_settings([Header(key="X-Team", value='{"team":"blue"}')], True)
    assert render_headers(
        settings.header_template, ConnectionSecret(access_token="onyx-token")
    ) == {"X-Team": '{"team":"blue"}', "Authorization": "Bearer onyx-token"}
