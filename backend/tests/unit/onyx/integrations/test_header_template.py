"""Saved header templates refuse headers that would change where a request goes."""

import pytest
from pydantic import ValidationError

from onyx.db.enums import IntegrationAuthMode
from onyx.integrations.connection_models import ConnectionSecret
from onyx.integrations.connections import render_headers
from onyx.server.features.integrations.models import IntegrationUpdate
from onyx.server.features.mcp.models import MCPAuthTemplate


@pytest.mark.parametrize(
    "headers",
    [{"Host": "internal.example.com"}, {"Bad Name": "x"}, {"X-A": "1", "x-a": "2"}],
)
def test_saved_templates_refuse_bad_header_names(headers: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        IntegrationUpdate(auth_mode=IntegrationAuthMode.SHARED, header_template=headers)
    with pytest.raises(ValidationError):
        MCPAuthTemplate(headers=headers)


def test_render_headers_drops_a_host_header() -> None:
    assert render_headers(
        {"host": "internal.example.com", "X-Key": "{api_key}"},
        ConnectionSecret(
            headers={"Host": "other.example.com"}, fields={"api_key": "k"}
        ),
    ) == {"X-Key": "k"}
