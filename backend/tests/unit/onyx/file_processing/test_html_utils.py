"""Coverage for the HTML-parsing helpers in ``onyx.file_processing.html_utils``
and the ``UnicodeDammit``-backed decoding in ``onyx.utils.web_content``.

Asserted strings are the literal output of the pinned ``beautifulsoup4`` version.
If an upgrade changes one, review the diff against real connector content before
updating the expected value.
"""

import pytest

import onyx.file_processing.html_utils as html_utils
from onyx.file_processing.enums import HtmlBasedConnectorTransformLinksStrategy
from onyx.file_processing.html_utils import format_document_soup
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.file_processing.html_utils import web_html_cleanup
from onyx.utils.web_content import decode_html_bytes

# ---------------------------------------------------------------------------
# format_document_soup / parse_html_page_basic (lxml parser)
# ---------------------------------------------------------------------------


def test_headings_and_paragraphs_are_newline_separated() -> None:
    html = (
        "<html><body>"
        "<h1>Title</h1><p>First paragraph.</p>"
        "<h2>Sub</h2><p>Second para.</p>"
        "</body></html>"
    )
    assert parse_html_page_basic(html) == "Title\nFirst paragraph.\nSub\nSecond para."


def test_unordered_list_items_get_hyphen_prefix() -> None:
    html = "<html><body><ul><li>one</li><li>two</li><li>three</li></ul></body></html>"
    assert parse_html_page_basic(html) == "- one\n- two\n- three"


def test_links_are_stripped_to_text_under_default_strategy() -> None:
    # Default HTML_BASED_CONNECTOR_TRANSFORM_LINKS_STRATEGY is STRIP, so the
    # href is dropped and only the anchor text survives.
    html = '<html><body><p>See <a href="https://example.com">this link</a> now.</p></body></html>'
    assert parse_html_page_basic(html) == "See this link now."


def test_links_become_markdown_under_markdown_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercises the bs4 href-extraction path (e.get("href")) by flipping the
    # module-level strategy the formatter reads at call time.
    monkeypatch.setattr(
        html_utils,
        "HTML_BASED_CONNECTOR_TRANSFORM_LINKS_STRATEGY",
        HtmlBasedConnectorTransformLinksStrategy.MARKDOWN,
    )
    # Keep the anchor as the last content: format_document_soup never clears
    # link_href (the "/a" reset branch is dead under bs4's .descendants), so any
    # text after a link leaks into its href. We assert only the correct behavior.
    html = '<html><body><p>See <a href="https://example.com">this link</a></p></body></html>'
    assert parse_html_page_basic(html) == "See [this link](https://example.com)"


def test_br_tag_produces_newline() -> None:
    html = "<html><body><p>line one<br>line two</p></body></html>"
    assert parse_html_page_basic(html) == "line one\nline two"


def test_table_rows_and_cells_use_tab_and_newline() -> None:
    html = (
        "<html><body><table>"
        "<tr><th>a</th><th>b</th></tr>"
        "<tr><td>1</td><td>2</td></tr>"
        "</table></body></html>"
    )
    assert parse_html_page_basic(html) == "a\tb\n\t1\t2"


def test_comments_and_doctype_are_excluded() -> None:
    html = "<!DOCTYPE html><html><body><!-- a comment --><p>visible</p></body></html>"
    assert parse_html_page_basic(html) == "visible"


def test_format_document_soup_accepts_prebuilt_soup() -> None:
    import bs4

    soup = bs4.BeautifulSoup("<p>hello</p><p>world</p>", "lxml")
    assert format_document_soup(soup) == "hello\nworld"


def test_div_blocks_are_newline_separated() -> None:
    html = "<html><body><div>one</div><div>two</div></body></html>"
    assert parse_html_page_basic(html) == "one\ntwo"


def test_ordered_list_items_also_get_hyphen_prefix() -> None:
    # <ol> shares the <li> handling with <ul>, so items are hyphenated rather
    # than numbered -- ordinal information is lost.
    html = "<html><body><ol><li>one</li><li>two</li></ol></body></html>"
    assert parse_html_page_basic(html) == "- one\n- two"


def test_nested_lists_are_flattened() -> None:
    # Nested <ul> nesting is not represented; every <li> is hyphenated at the
    # same level regardless of depth.
    html = "<html><body><ul><li>a<ul><li>b</li></ul></li></ul></body></html>"
    assert parse_html_page_basic(html) == "- a\n- b"


def test_adjacent_inline_elements_get_separating_space() -> None:
    # Sibling inline elements with no whitespace between them are joined with a
    # single space so their text doesn't run together.
    html = "<html><body><span>a</span><span>b</span></body></html>"
    assert parse_html_page_basic(html) == "a b"


def test_repeated_whitespace_and_blank_lines_are_collapsed() -> None:
    html = (
        "<html><body><p>lots    of     space</p>\n\n\n"
        "<p>and    newlines</p></body></html>"
    )
    assert parse_html_page_basic(html) == "lots of space\nand newlines"


def test_blank_input_returns_empty_string() -> None:
    assert parse_html_page_basic("") == ""
    assert parse_html_page_basic("   \n  ") == ""


# ---------------------------------------------------------------------------
# web_html_cleanup (title extraction + class/element stripping)
# ---------------------------------------------------------------------------


def test_web_html_cleanup_extracts_title_and_strips_noise() -> None:
    html = """<html><head><title>My Page Title</title></head><body>
<nav>navigation junk</nav>
<div class="sidebar">sidebar junk</div>
<footer>footer junk</footer>
<div class="content"><h1>Heading</h1><p>Real content here.</p></div>
<script>var x = 1;</script>
</body></html>"""
    result = web_html_cleanup(html)
    assert result.title == "My Page Title"
    assert result.cleaned_text == "Heading\nReal content here."


def test_web_html_cleanup_mintlify_classes_removed_when_enabled() -> None:
    html = (
        "<html><head><title>T</title></head><body>"
        '<div class="hidden">hidden junk</div>'
        '<div class="sticky">sticky junk</div>'
        "<p>keep me</p>"
        "</body></html>"
    )
    assert web_html_cleanup(html).cleaned_text == "keep me"


def test_web_html_cleanup_mintlify_classes_kept_when_disabled() -> None:
    html = (
        "<html><head><title>T</title></head><body>"
        '<div class="hidden">hidden junk</div>'
        '<div class="sticky">sticky junk</div>'
        "<p>keep me</p>"
        "</body></html>"
    )
    cleaned = web_html_cleanup(html, mintlify_cleanup_enabled=False).cleaned_text
    assert cleaned == "hidden junk\nsticky junk\nkeep me"


def test_web_html_cleanup_additional_element_types_discarded() -> None:
    # <header> isn't in the default ignored elements, so its removal is
    # attributable to additional_element_types_to_discard rather than the config.
    html = (
        "<html><head><title>T</title></head><body>"
        "<header>head junk</header><p>body text</p>"
        "</body></html>"
    )
    cleaned = web_html_cleanup(
        html, additional_element_types_to_discard=["header"]
    ).cleaned_text
    assert cleaned == "body text"


def test_web_html_cleanup_returns_none_title_when_absent() -> None:
    result = web_html_cleanup("<html><body><p>hi</p></body></html>")
    assert result.title is None
    assert result.cleaned_text == "hi"


def test_web_html_cleanup_matches_whole_class_tokens_only() -> None:
    # Ignored classes are matched against whitespace-split tokens, so "sidebar"
    # drops an element only when it's a standalone class, not a substring.
    html = (
        "<html><head><title>T</title></head><body>"
        '<div class="sidebarwide">substring kept</div>'
        '<div class="main sidebar extra">token dropped</div>'
        "<p>body</p>"
        "</body></html>"
    )
    assert web_html_cleanup(html).cleaned_text == "substring kept\nbody"


def test_web_html_cleanup_strips_zero_width_spaces() -> None:
    # U+200B (zero-width space) is dropped from the cleaned text.
    html = "<html><head><title>T</title></head><body><p>a\u200bb</p></body></html>"
    assert web_html_cleanup(html).cleaned_text == "ab"


# ---------------------------------------------------------------------------
# decode_html_bytes (bs4.dammit.UnicodeDammit)
# ---------------------------------------------------------------------------


def test_decode_latin1_without_hint() -> None:
    assert decode_html_bytes("café".encode("iso-8859-1")) == "café"


def test_decode_latin1_with_charset_content_type() -> None:
    content = "café".encode("iso-8859-1")
    decoded = decode_html_bytes(content, content_type="text/html; charset=iso-8859-1")
    assert decoded == "café"


def test_decode_latin1_with_fallback_encoding() -> None:
    content = "café".encode("iso-8859-1")
    assert decode_html_bytes(content, fallback_encoding="iso-8859-1") == "café"


def test_decode_utf8_roundtrip() -> None:
    content = "café — naïve".encode("utf-8")
    assert decode_html_bytes(content) == "café — naïve"


def test_decode_respects_html_meta_charset() -> None:
    html = b'<html><head><meta charset="iso-8859-1"></head><body>caf\xe9</body></html>'
    decoded = decode_html_bytes(html)
    assert "café" in decoded


def test_decode_content_type_charset_overrides_meta_charset() -> None:
    # content_type charset is registered as an override encoding, so it wins over
    # a conflicting <meta charset>. Here the bytes are iso-8859-1 but meta lies
    # and claims utf-8; the iso-8859-1 hint from content_type decodes correctly.
    html = '<html><head><meta charset="utf-8"></head><body>café</body></html>'.encode(
        "iso-8859-1"
    )
    decoded = decode_html_bytes(html, content_type="text/html; charset=iso-8859-1")
    assert "café" in decoded


def test_decode_empty_bytes_returns_empty_string() -> None:
    assert decode_html_bytes(b"") == ""


def test_decode_unknown_charset_falls_back_to_sniffing() -> None:
    # An unusable charset hint is ignored rather than raising; UnicodeDammit
    # sniffs the actual (utf-8) encoding.
    content = "café".encode("utf-8")
    assert (
        decode_html_bytes(content, content_type="text/html; charset=not-a-real-charset")
        == "café"
    )
