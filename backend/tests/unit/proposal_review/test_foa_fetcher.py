"""Unit tests for the FOA fetcher engine component.

Tests cover:
- _determine_domain: opportunity ID prefix -> agency domain mapping
- fetch_foa: search flow with mocked web search provider and crawler
- Graceful failure when no web search provider is configured
- Empty / missing opportunity ID handling
"""

from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.server.features.proposal_review.engine.foa_fetcher import _determine_domain
from onyx.server.features.proposal_review.engine.foa_fetcher import fetch_foa


# =====================================================================
# _determine_domain  --  prefix -> domain mapping
# =====================================================================


class TestDetermineDomain:
    """Tests for _determine_domain (opportunity ID prefix detection)."""

    @pytest.mark.parametrize(
        "opp_id, expected_domain",
        [
            ("RFA-AI-24-001", "grants.nih.gov"),
            ("PA-24-123", "grants.nih.gov"),
            ("PAR-24-100", "grants.nih.gov"),
            ("R01-AI-12345", "grants.nih.gov"),
            ("R21-GM-67890", "grants.nih.gov"),
            ("U01-CA-11111", "grants.nih.gov"),
            ("NOT-OD-24-100", "grants.nih.gov"),
            ("NSF-24-567", "nsf.gov"),
            ("DE-FOA-0003000", "energy.gov"),
            ("HRSA-25-001", "hrsa.gov"),
            ("W911NF-24-R-0001", "grants.gov"),
            ("FA8750-24-S-0001", "grants.gov"),
            ("N00014-24-S-0001", "grants.gov"),
            ("NOFO-2024-001", "grants.gov"),
        ],
    )
    def test_known_prefixes(self, opp_id, expected_domain):
        assert _determine_domain(opp_id) == expected_domain

    def test_unknown_prefix_returns_none(self):
        assert _determine_domain("UNKNOWN-123") is None

    def test_purely_numeric_id_returns_grants_gov(self):
        assert _determine_domain("12345-67890") == "grants.gov"

    def test_case_insensitive_matching(self):
        assert _determine_domain("rfa-ai-24-001") == "grants.nih.gov"
        assert _determine_domain("nsf-24-567") == "nsf.gov"

    def test_empty_string_returns_none(self):
        # Empty string is not purely numeric after dash removal, so returns None
        assert _determine_domain("") is None


# =====================================================================
# fetch_foa  --  search flow
# =====================================================================


class TestFetchFoa:
    """Tests for fetch_foa with mocked dependencies."""

    def _mock_db_session(self, existing_foa=None):
        """Build a mock db_session that returns existing_foa for the FOA query."""
        db_session = MagicMock()
        query_mock = MagicMock()
        db_session.query.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = existing_foa
        return db_session

    def test_empty_opportunity_id_returns_none(self):
        db = MagicMock()
        assert fetch_foa("", uuid4(), db) is None
        assert fetch_foa("   ", uuid4(), db) is None

    def test_none_opportunity_id_returns_none(self):
        db = MagicMock()
        assert fetch_foa(None, uuid4(), db) is None  # type: ignore[arg-type]

    def test_existing_foa_is_returned_without_search(self):
        existing = MagicMock()
        existing.extracted_text = "Previously fetched FOA content."
        db = self._mock_db_session(existing_foa=existing)

        result = fetch_foa("RFA-AI-24-001", uuid4(), db)
        assert result == "Previously fetched FOA content."

    def test_search_flow_fetches_and_saves(self):
        """Full happy-path: search returns a URL, crawler fetches content, doc is saved."""
        # Setup: no existing FOA
        db = self._mock_db_session(existing_foa=None)

        # Mock the web search provider
        search_result = MagicMock()
        search_result.link = "https://grants.nih.gov/foa/RFA-AI-24-001"
        provider = MagicMock()
        provider.search.return_value = [search_result]

        # Mock the crawler
        content = MagicMock()
        content.scrape_successful = True
        content.full_content = "Full FOA text from NIH."
        crawler_instance = MagicMock()
        crawler_instance.contents.return_value = [content]

        # The function does lazy imports, so we patch at the module level
        # where the imports happen
        import_target_provider = (
            "onyx.tools.tool_implementations.web_search.providers.get_default_provider"
        )
        import_target_crawler = (
            "onyx.tools.tool_implementations.open_url.onyx_web_crawler.OnyxWebCrawler"
        )

        with (
            patch(import_target_provider, return_value=provider),
            patch(import_target_crawler, return_value=crawler_instance),
        ):
            result = fetch_foa("RFA-AI-24-001", uuid4(), db)

        assert result == "Full FOA text from NIH."
        db.add.assert_called_once()
        db.flush.assert_called_once()

    def test_no_provider_configured_returns_none(self):
        """If get_default_provider raises or returns None, fetch_foa returns None."""
        db = self._mock_db_session(existing_foa=None)

        import_target = (
            "onyx.tools.tool_implementations.web_search.providers.get_default_provider"
        )
        with patch(import_target, return_value=None):
            result = fetch_foa("RFA-AI-24-001", uuid4(), db)

        assert result is None

    def test_provider_import_failure_returns_none(self):
        """If the web search provider module can't be imported, returns None."""
        db = self._mock_db_session(existing_foa=None)

        import_target = (
            "onyx.tools.tool_implementations.web_search.providers.get_default_provider"
        )
        with patch(import_target, side_effect=ImportError("module not found")):
            result = fetch_foa("RFA-AI-24-001", uuid4(), db)

        assert result is None

    def test_search_returns_no_results(self):
        """If the search returns an empty list, fetch_foa returns None."""
        db = self._mock_db_session(existing_foa=None)

        provider = MagicMock()
        provider.search.return_value = []

        import_target = (
            "onyx.tools.tool_implementations.web_search.providers.get_default_provider"
        )
        with patch(import_target, return_value=provider):
            result = fetch_foa("NSF-24-567", uuid4(), db)

        assert result is None

    def test_crawler_failure_returns_none(self):
        """If the crawler raises an exception, fetch_foa returns None."""
        db = self._mock_db_session(existing_foa=None)

        search_result = MagicMock()
        search_result.link = "https://nsf.gov/foa/24-567"
        provider = MagicMock()
        provider.search.return_value = [search_result]

        import_target_provider = (
            "onyx.tools.tool_implementations.web_search.providers.get_default_provider"
        )
        import_target_crawler = (
            "onyx.tools.tool_implementations.open_url.onyx_web_crawler.OnyxWebCrawler"
        )

        with (
            patch(import_target_provider, return_value=provider),
            patch(import_target_crawler, side_effect=Exception("crawl failed")),
        ):
            result = fetch_foa("NSF-24-567", uuid4(), db)

        assert result is None

    def test_scrape_unsuccessful_returns_none(self):
        """If the crawler succeeds but scrape_successful is False, returns None."""
        db = self._mock_db_session(existing_foa=None)

        search_result = MagicMock()
        search_result.link = "https://nsf.gov/foa/24-567"
        provider = MagicMock()
        provider.search.return_value = [search_result]

        content = MagicMock()
        content.scrape_successful = False
        content.full_content = None
        crawler_instance = MagicMock()
        crawler_instance.contents.return_value = [content]

        import_target_provider = (
            "onyx.tools.tool_implementations.web_search.providers.get_default_provider"
        )
        import_target_crawler = (
            "onyx.tools.tool_implementations.open_url.onyx_web_crawler.OnyxWebCrawler"
        )

        with (
            patch(import_target_provider, return_value=provider),
            patch(import_target_crawler, return_value=crawler_instance),
        ):
            result = fetch_foa("NSF-24-567", uuid4(), db)

        assert result is None
