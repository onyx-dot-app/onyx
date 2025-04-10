from __future__ import annotations

import datetime
import tempfile
from collections.abc import Iterable

import pytest
import pywikibot  # type: ignore[import-untyped]
from pytest_mock import MockFixture

from onyx.connectors.mediawiki import wiki

# Some of these tests are disabled for now due to flakiness with wikipedia as the backend

pywikibot.config.base_dir = tempfile.TemporaryDirectory().name


@pytest.fixture
def site() -> pywikibot.Site:
    return pywikibot.Site("en", "wikipedia")


def test_pywikibot_timestamp_to_utc_datetime() -> None:
    timestamp_without_tzinfo = pywikibot.Timestamp(2023, 12, 27, 15, 38, 49)
    timestamp_min_timezone = timestamp_without_tzinfo.astimezone(datetime.timezone.min)
    timestamp_max_timezone = timestamp_without_tzinfo.astimezone(datetime.timezone.max)
    assert timestamp_min_timezone.tzinfo == datetime.timezone.min
    assert timestamp_max_timezone.tzinfo == datetime.timezone.max
    for timestamp in [
        timestamp_without_tzinfo,
        timestamp_min_timezone,
        timestamp_max_timezone,
    ]:
        dt = wiki.pywikibot_timestamp_to_utc_datetime(timestamp)
        assert dt.tzinfo == datetime.timezone.utc


class MockPage(pywikibot.Page):
    def __init__(
        self, site: pywikibot.Site, title: str, _has_categories: bool = False
    ) -> None:
        super().__init__(site, title)
        self._has_categories = _has_categories
        self.header = "This is a header"
        self._sections = ["This is a section", "This is another section"]

    @property
    def _sections_helper(self) -> list[str]:
        return [
            f"== Section {i} ==\n{section}\n"
            for i, section in enumerate(self._sections)
        ]

    @property
    def text(self) -> str:
        text = self.header + "\n"
        for section in self._sections_helper:
            text += section
        return text

    @property
    def pageid(self) -> str:
        return "1"

    def full_url(self) -> str:
        return "Test URL"

    def categories(
        self,
        with_sort_key: bool = False,
        total: int | None = None,
        content: bool = False,
    ) -> Iterable[pywikibot.Page]:
        if not self._has_categories:
            return []
        return [
            MockPage(self.site, "Test Category1"),
            MockPage(self.site, "Test Category2"),
        ]

    @property
    def latest_revision(self) -> pywikibot.page.Revision:
        return pywikibot.page.Revision(
            timestamp=pywikibot.Timestamp(2023, 12, 27, 15, 38, 49)
        )


@pytest.mark.skip(reason="Test disabled")
def test_get_doc_from_page(site: pywikibot.Site) -> None:
    test_page = MockPage(site, "Test Page", _has_categories=True)
    doc = wiki.get_doc_from_page(test_page, site, wiki.DocumentSource.MEDIAWIKI)
    assert doc.source == wiki.DocumentSource.MEDIAWIKI
    assert doc.title == test_page.title()
    assert doc.doc_updated_at == wiki.pywikibot_timestamp_to_utc_datetime(
        test_page.latest_revision.timestamp
    )
    assert len(doc.sections) == 3
    for section, expected_section in zip(
        doc.sections, test_page._sections_helper + [test_page.header]
    ):
        assert (
            section.text is not None
            and section.text.strip() == expected_section.strip()
        )  # Extra whitespace before/after is okay
        assert section.link and section.link.startswith(test_page.full_url())
    assert doc.semantic_identifier == test_page.title()
    assert doc.metadata == {
        "categories": [category.title() for category in test_page.categories()]
    }
    assert doc.id == f"MEDIAWIKI_{test_page.pageid}_{test_page.full_url()}"


@pytest.mark.skip(reason="Test disabled")
def test_mediawiki_connector_recurse_depth() -> None:
    """Test that the recurse_depth parameter is parsed correctly.

    -1 should be parsed as `True` (for unbounded recursion)
    0 or greater should be parsed as an integer
    Negative values less than -1 should raise a ValueError

    This is the specification dictated by the `pywikibot` library. We do not need to test behavior beyond this.
    """
    hostname = "wikipedia.org"
    categories: list[str] = []
    pages = ["Test Page"]

    # Recurse depth less than -1 raises ValueError
    with pytest.raises(ValueError):
        recurse_depth = -2
        wiki.MediaWikiConnector(hostname, categories, pages, recurse_depth)

    # Recurse depth of -1 gets parsed as `True`
    recurse_depth = -1
    connector = wiki.MediaWikiConnector(hostname, categories, pages, recurse_depth)
    assert connector.recurse_depth is True

    # Recurse depth of 0 or greater gets parsed as an integer
    recurse_depth = 0
    connector = wiki.MediaWikiConnector(hostname, categories, pages, recurse_depth)
    assert connector.recurse_depth == recurse_depth


@pytest.mark.skip(reason="Test disabled")
def test_load_from_state_calls_poll_source_with_nones(mocker: MockFixture) -> None:
    connector = wiki.MediaWikiConnector("wikipedia.org", [], [], 0, "test")
    poll_source = mocker.patch.object(connector, "poll_source")
    connector.load_from_state()
    poll_source.assert_called_once_with(None, None)
