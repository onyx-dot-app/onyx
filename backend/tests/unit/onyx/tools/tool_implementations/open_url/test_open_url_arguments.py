import pytest
from pydantic import JsonValue

from onyx.tools.interface import parse_tool_arguments
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.open_url.models import OpenURLArguments


@pytest.mark.parametrize(
    ("urls", "cleaned"),
    [
        ("https://a.com", ["https://a.com"]),
        (
            ["  https://a.com ", "", "https://b.com", "https://a.com"],
            ["https://a.com", "https://b.com"],
        ),
    ],
)
def test_urls_are_stripped_and_deduplicated_in_order(
    urls: JsonValue, cleaned: list[str]
) -> None:
    assert parse_tool_arguments(OpenURLArguments, {"urls": urls}).urls == cleaned


@pytest.mark.parametrize(
    "arguments", [{}, {"urls": None}, {"urls": []}, {"urls": ["", "  "]}]
)
def test_no_url_is_a_missing_argument(arguments: dict[str, JsonValue]) -> None:
    with pytest.raises(
        ToolCallException, match="^Invalid tool arguments: urls: Field required$"
    ):
        parse_tool_arguments(OpenURLArguments, arguments)


def test_urls_must_be_a_string_or_a_list() -> None:
    with pytest.raises(ToolCallException, match="urls: .*a string or a list"):
        parse_tool_arguments(OpenURLArguments, {"urls": 42})
