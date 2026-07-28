from onyx.configs.constants import MASK_CREDENTIAL_CHAR
from onyx.db.models import Tool
from onyx.server.features.tool.models import ToolSnapshot


def _make_tool() -> Tool:
    return Tool(
        id=1,
        name="my_custom_tool",
        description="calls an internal API",
        display_name="My Custom Tool",
        in_code_tool_id=None,
        openapi_schema={"openapi": "3.0.0"},
        custom_headers=[
            {"key": "Authorization", "value": "Bearer super-secret-token-12345"},
            {"key": "X-Api-Key", "value": "sk-abcdef0123456789"},
        ],
        passthrough_auth=False,
        user_id=None,
        enabled=True,
    )


def test_from_model_masks_header_values_by_default() -> None:
    snapshot = ToolSnapshot.from_model(_make_tool())

    assert snapshot.custom_headers is not None
    for header in snapshot.custom_headers:
        assert MASK_CREDENTIAL_CHAR in header["value"]
        assert "secret" not in header["value"]
        assert "sk-" not in header["value"]
    # Keys stay visible so the admin UI can still show which headers exist.
    assert [h["key"] for h in snapshot.custom_headers] == [
        "Authorization",
        "X-Api-Key",
    ]


def test_from_model_returns_raw_values_when_explicitly_requested() -> None:
    snapshot = ToolSnapshot.from_model(_make_tool(), include_secret_header_values=True)

    assert snapshot.custom_headers == [
        {"key": "Authorization", "value": "Bearer super-secret-token-12345"},
        {"key": "X-Api-Key", "value": "sk-abcdef0123456789"},
    ]


def test_from_model_handles_missing_headers() -> None:
    tool = _make_tool()
    tool.custom_headers = None
    assert ToolSnapshot.from_model(tool).custom_headers is None

    tool.custom_headers = []
    assert ToolSnapshot.from_model(tool).custom_headers == []
