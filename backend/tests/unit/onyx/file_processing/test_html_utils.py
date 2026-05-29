"""Baseline coverage for BeautifulSoup-backed HTML parsing.

These tests pin the *current* observable behavior of the HTML-parsing helpers in
``onyx.file_processing.html_utils`` and the ``UnicodeDammit``-backed decoding in
``onyx.utils.web_content``. They exist to catch behavioral drift when the
``beautifulsoup4`` dependency is upgraded -- the asserted strings are the literal
output produced by the pinned baseline version, not aspirational formatting.

If a future bs4 upgrade changes one of these outputs, that is a signal to review
the diff against real connector content, not to blindly update the expected value.
"""

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


def test_links_become_markdown_under_markdown_strategy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Exercises the bs4 href-extraction path (e.get("href")) by flipping the
    # module-level strategy the formatter reads at call time.
    monkeypatch.setattr(
        html_utils,
        "HTML_BASED_CONNECTOR_TRANSFORM_LINKS_STRATEGY",
        HtmlBasedConnectorTransformLinksStrategy.MARKDOWN,
    )
    # NOTE: the trailing " now." also gets wrapped as a link. The formatter only
    # clears link_href when it sees an "/a" tag, but bs4 never emits a closing
    # pseudo-tag in .descendants, so the href leaks onto following text. This is a
    # latent quirk in format_document_soup -- pinned here so a bs4 upgrade that
    # changes descendant iteration is caught rather than silently altering output.
    html = '<html><body><p>See <a href="https://example.com">this link</a> now.</p></body></html>'
    assert (
        parse_html_page_basic(html)
        == "See [this link](https://example.com) [ now.](https://example.com)"
    )


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
    html = (
        "<html><head><title>T</title></head><body>"
        "<header>head junk</header><aside>aside</aside><p>body text</p>"
        "</body></html>"
    )
    cleaned = web_html_cleanup(
        html, additional_element_types_to_discard=["header"]
    ).cleaned_text
    assert cleaned == "body text"


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
