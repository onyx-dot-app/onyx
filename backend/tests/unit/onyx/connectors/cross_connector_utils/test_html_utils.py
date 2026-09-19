import pathlib

import pytest

import onyx.file_processing.html_utils as html_utils
from onyx.file_processing.enums import HtmlBasedConnectorTransformLinksStrategy
from onyx.file_processing.html_utils import parse_html_page_basic


def test_parse_table() -> None:
    dir_path = pathlib.Path(__file__).parent.resolve()
    with open(f"{dir_path}/test_table.html", "r") as file:
        content = file.read()

    parsed = parse_html_page_basic(content)
    expected = "\n\thello\tthere\tgeneral\n\tkenobi\ta\tb\n\tc\td\te"
    assert expected in parsed


def test_content_after_table_uses_normal_block_formatting() -> None:
    html = (
        "<p>before</p>"
        "<table><tr><td>cell</td></tr></table>"
        "<h2>after heading</h2>"
        "<p>after paragraph</p>"
        "<ul><li>one</li><li>two</li></ul>"
    )

    assert parse_html_page_basic(html) == (
        "before\n\tcell\nafter heading\nafter paragraph\n- one\n- two"
    )


def test_markdown_link_ends_at_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        html_utils,
        "HTML_BASED_CONNECTOR_TRANSFORM_LINKS_STRATEGY",
        HtmlBasedConnectorTransformLinksStrategy.MARKDOWN,
    )
    html = (
        '<p>See <a href="https://example.com">this link</a> now.</p>'
        "<p>Next paragraph.</p>"
    )

    assert parse_html_page_basic(html) == (
        "See [this link](https://example.com) now.\nNext paragraph."
    )
