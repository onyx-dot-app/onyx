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


def test_punctuation_after_an_inline_element_keeps_its_word() -> None:
    """A browser renders no gap between `</b>` and the `!` that follows it."""
    html = "<p>Hello <b>world</b>! See <i>this</i>.</p>"

    assert parse_html_page_basic(html) == "Hello world! See this."


def test_punctuation_around_an_inline_element_keeps_its_word() -> None:
    html = "<p>A <b>bold</b>, a <i>slant</i>; and (<b>x</b>) too.</p>"

    assert parse_html_page_basic(html) == "A bold, a slant; and (x) too."


def test_two_adjacent_elements_are_still_separated() -> None:
    """The spacing rule is still what keeps two words apart."""
    assert parse_html_page_basic("<span>a</span><span>b</span>") == "a b"


@pytest.mark.parametrize(
    "html,expected",
    [
        ("<p><b>Don</b>'t stop</p>", "Don't stop"),
        ("<p><b>John</b>'s book</p>", "John's book"),
        ('<p>He said "<b>no</b>" twice</p>', 'He said "no" twice'),
        ("<p>A '<i>word</i>' here</p>", "A 'word' here"),
        ('<p>("<i>x</i>")</p>', '("x")'),
    ],
)
def test_a_straight_quote_attaches_to_the_word_it_belongs_to(
    html: str, expected: str
) -> None:
    assert parse_html_page_basic(html) == expected


def test_a_closing_straight_quote_still_leaves_a_gap_before_the_next_element() -> None:
    assert parse_html_page_basic('<p>"<i>a</i>"<i>b</i></p>') == '"a" b'
