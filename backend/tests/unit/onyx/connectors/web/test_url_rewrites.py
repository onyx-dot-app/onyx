"""Unit tests for the web connector's URL rewrite helpers."""

from unittest.mock import patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.connectors.web.connector import _parse_url_rewrites
from onyx.connectors.web.connector import _rewrite_url
from onyx.connectors.web.connector import ScrapeResult
from onyx.connectors.web.connector import WebConnector


def test_parse_url_rewrites_pairs() -> None:
    """The admin form submits [source, target] pairs."""
    parsed = _parse_url_rewrites(
        [
            ["https://mirror.internal", "https://docs.example.com"],
            ["http://a", "http://b"],
        ]
    )
    assert parsed == {
        "https://mirror.internal": "https://docs.example.com",
        "http://a": "http://b",
    }


def test_parse_url_rewrites_arrow_strings() -> None:
    """Hand-written API configs may use "source -> target" strings."""
    parsed = _parse_url_rewrites(
        [
            "https://mirror.internal -> https://docs.example.com",
            "http://a -> http://b",
        ]
    )
    assert parsed == {
        "https://mirror.internal": "https://docs.example.com",
        "http://a": "http://b",
    }


def test_parse_url_rewrites_skips_invalid_entries() -> None:
    parsed = _parse_url_rewrites(
        [
            "no-arrow-here",  # no separator
            " -> https://target.only",  # empty source
            "https://source.only -> ",  # empty target
            ["https://one.element"],  # not a pair
            ["", "https://empty.source"],  # empty pair source
            ["https://ok", "https://fine"],
        ]
    )
    assert parsed == {"https://ok": "https://fine"}


def test_rewrite_url_first_matching_prefix_wins() -> None:
    rewrites = {
        "https://mirror.internal/docs": "https://docs.example.com",
        "https://mirror.internal": "https://www.example.com",
    }
    assert (
        _rewrite_url("https://mirror.internal/docs/page", rewrites)
        == "https://docs.example.com/page"
    )
    assert (
        _rewrite_url("https://mirror.internal/blog", rewrites)
        == "https://www.example.com/blog"
    )


def test_rewrite_url_replaces_prefix_only_once() -> None:
    rewrites = {"https://a": "https://b"}
    # Only the leading prefix is replaced, not later occurrences in the path.
    assert (
        _rewrite_url("https://a/redirect?to=https://a", rewrites)
        == "https://b/redirect?to=https://a"
    )


def test_rewrite_url_no_match_returns_unchanged() -> None:
    assert _rewrite_url("https://other.example.com/x", {"https://a": "https://b"}) == (
        "https://other.example.com/x"
    )


def test_web_connector_parses_url_rewrites() -> None:
    connector = WebConnector(
        base_url="https://mirror.internal/docs",
        web_connector_type="single",
        url_rewrites=[["https://mirror.internal", "https://docs.example.com"]],
    )
    assert connector.url_rewrites == {
        "https://mirror.internal": "https://docs.example.com"
    }


def test_web_connector_defaults_to_no_rewrites() -> None:
    connector = WebConnector(
        base_url="https://docs.example.com",
        web_connector_type="single",
    )
    assert connector.url_rewrites == {}


def test_colliding_rewritten_ids_emit_only_first_document() -> None:
    """Two fetched URLs can rewrite to the same storage id (e.g. crawling a
    mirror and the canonical site); only the first document may be emitted or
    the later one would overwrite it in the index."""
    connector = WebConnector(
        base_url="https://mirror.internal/page",
        web_connector_type="single",
        url_rewrites=[["https://mirror.internal", "https://docs.example.com"]],
    )
    connector.to_visit_list = [
        "https://mirror.internal/page",
        "https://docs.example.com/page",
    ]

    def _fake_scrape(
        index: int,  # noqa: ARG001
        initial_url: str,  # noqa: ARG001
        session_ctx: object,  # noqa: ARG001
        slim: bool = False,  # noqa: ARG001
    ) -> ScrapeResult:
        result = ScrapeResult()
        result.doc = Document(
            id="https://docs.example.com/page",
            sections=[TextSection(link="https://docs.example.com/page", text="x")],
            source=DocumentSource.WEB,
            semantic_identifier="page",
            metadata={},
        )
        return result

    with (
        patch(
            "onyx.connectors.web.connector.ScrapeSessionContext.initialize",
        ),
        patch("onyx.connectors.web.connector.check_internet_connection"),
        patch("onyx.connectors.web.connector.protected_url_check"),
        patch.object(WebConnector, "_do_scrape", side_effect=_fake_scrape),
    ):
        docs = [doc for batch in connector.load_from_state() for doc in batch]

    assert [doc.id for doc in docs if isinstance(doc, Document)] == [
        "https://docs.example.com/page"
    ]
    assert len(docs) == 1
