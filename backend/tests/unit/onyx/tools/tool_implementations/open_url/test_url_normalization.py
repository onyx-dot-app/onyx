"""Unit tests for URL normalization module."""

import pytest

from onyx.configs.constants import DocumentSource
from onyx.tools.tool_implementations.open_url.open_url_tool import _url_lookup_variants
from onyx.tools.tool_implementations.open_url.url_normalization import (
    _detect_source_type,
)
from onyx.tools.tool_implementations.open_url.url_normalization import normalize_url


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://docs.google.com/document/d/1ABC123/edit?tab=t.0",
            "https://docs.google.com/document/d/1ABC123",
        ),
        (
            "https://docs.google.com/document/d/1ABC123/view",
            "https://docs.google.com/document/d/1ABC123",
        ),
        (
            "https://docs.google.com/document/d/1ABC123",
            "https://docs.google.com/document/d/1ABC123",
        ),
        (
            "https://drive.google.com/file/d/1ABC123/view?usp=sharing",
            "https://drive.google.com/file/d/1ABC123",
        ),
        (
            "https://drive.google.com/open?id=1ABC123",
            "https://drive.google.com/file/d/1ABC123",
        ),
        (
            "https://docs.google.com/document/d/1TVE04FYWmyP9j-OJFYcG3tnaLeqBbZ1pauCvmYkNq7c/edit?tab=t.0",
            "https://docs.google.com/document/d/1TVE04FYWmyP9j-OJFYcG3tnaLeqBbZ1pauCvmYkNq7c",
        ),
    ],
)
def test_google_drive_normalization(url: str, expected: str) -> None:
    """Test Google Drive URL normalization."""
    assert normalize_url(url, source_type=DocumentSource.GOOGLE_DRIVE) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://notion.so/Page-1234567890abcdef1234567890abcdef",
            "12345678-90ab-cdef-1234-567890abcdef",
        ),
        (
            "https://notion.so/page?p=1234567890abcdef1234567890abcdef",
            "12345678-90ab-cdef-1234-567890abcdef",
        ),
        # Edge case: URL with title prefix but valid UUID
        (
            "https://www.notion.so/My-Page-abc123def456ghi789jkl012mno345pq",
            None,  # May not extract correctly if UUID is incomplete
        ),
    ],
)
def test_notion_normalization(url: str, expected: str | None) -> None:
    """Test Notion URL normalization (extracts page ID as UUID)."""
    result = normalize_url(url, source_type=DocumentSource.NOTION)
    assert result == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://workspace.slack.com/archives/C1234567890/p1234567890123456",
            "C1234567890__1234567890.123456",
        ),
        (
            "https://workspace.slack.com/archives/C1234567890/p1234567890123456?thread_ts=1234567890.123456",
            "C1234567890__1234567890.123456",
        ),
    ],
)
def test_slack_normalization(url: str, expected: str) -> None:
    """Test Slack URL normalization (extracts channel_id__thread_ts format)."""
    assert normalize_url(url, source_type=DocumentSource.SLACK) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://example.atlassian.net/wiki/spaces/SPACE/pages/12345?query=param#section",
            "https://example.atlassian.net/wiki/spaces/SPACE/pages/12345",
        ),
        (
            "https://example.atlassian.net/wiki/spaces/SPACE/pages/12345",
            "https://example.atlassian.net/wiki/spaces/SPACE/pages/12345",
        ),
    ],
)
def test_confluence_normalization(url: str, expected: str) -> None:
    """Test Confluence URL normalization (uses default normalizer)."""
    assert normalize_url(url, source_type=DocumentSource.CONFLUENCE) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://example.atlassian.net/jira/browse/PROJ-123?query=param#section",
            "https://example.atlassian.net/jira/browse/PROJ-123",
        ),
        (
            "https://example.atlassian.net/jira/software/projects/PROJ/issues/PROJ-123",
            "https://example.atlassian.net/jira/software/projects/PROJ/issues/PROJ-123",
        ),
    ],
)
def test_jira_normalization(url: str, expected: str) -> None:
    """Test Jira URL normalization (uses default normalizer)."""
    assert normalize_url(url, source_type=DocumentSource.JIRA) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://github.com/owner/repo/blob/main/file.py?query=param#section",
            "https://github.com/owner/repo/blob/main/file.py",
        ),
        (
            "https://github.com/owner/repo/blob/main/file.py",
            "https://github.com/owner/repo/blob/main/file.py",
        ),
    ],
)
def test_github_normalization(url: str, expected: str) -> None:
    """Test GitHub URL normalization (uses default normalizer)."""
    assert normalize_url(url, source_type=DocumentSource.GITHUB) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://gitlab.com/owner/repo/-/blob/main/file.py?query=param#section",
            "https://gitlab.com/owner/repo/-/blob/main/file.py",
        ),
    ],
)
def test_gitlab_normalization(url: str, expected: str) -> None:
    """Test GitLab URL normalization (uses default normalizer)."""
    assert normalize_url(url, source_type=DocumentSource.GITLAB) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://example.sharepoint.com/sites/Site/Doc.aspx?query=param#section",
            "https://example.sharepoint.com/sites/Site/Doc.aspx",
        ),
    ],
)
def test_sharepoint_normalization(url: str, expected: str) -> None:
    """Test SharePoint URL normalization (uses default normalizer)."""
    assert normalize_url(url, source_type=DocumentSource.SHAREPOINT) == expected


@pytest.mark.parametrize(
    "url,expected_source",
    [
        (
            "https://docs.google.com/document/d/1ABC123/edit",
            DocumentSource.GOOGLE_DRIVE,
        ),
        ("https://drive.google.com/file/d/123", DocumentSource.GOOGLE_DRIVE),
        ("https://www.notion.so/Page-abc123def456", DocumentSource.NOTION),
        ("https://notion.site/page", DocumentSource.NOTION),
        (
            "https://example.atlassian.net/wiki/spaces/SPACE/pages/123",
            DocumentSource.CONFLUENCE,
        ),
        ("https://example.atlassian.net/jira/browse/PROJ-123", DocumentSource.JIRA),
        ("https://github.com/owner/repo/blob/main/file.py", DocumentSource.GITHUB),
        ("https://gitlab.com/owner/repo", DocumentSource.GITLAB),
        ("https://example.sharepoint.com/sites/Site", DocumentSource.SHAREPOINT),
        ("https://workspace.slack.com/archives/C123/p456", DocumentSource.SLACK),
        ("https://example.com/doc", None),  # Unknown source
    ],
)
def test_detect_source_type(url: str, expected_source: DocumentSource | None) -> None:
    """Test source type detection from URL patterns."""
    assert _detect_source_type(url) == expected_source


@pytest.mark.parametrize(
    "url,expected_source,expected_normalized",
    [
        (
            "https://docs.google.com/document/d/1ABC123/edit",
            DocumentSource.GOOGLE_DRIVE,
            "https://docs.google.com/document/d/1ABC123",
        ),
        (
            "https://www.notion.so/Page-1234567890abcdef1234567890abcdef",
            DocumentSource.NOTION,
            "12345678-90ab-cdef-1234-567890abcdef",
        ),
        (
            "https://example.atlassian.net/wiki/spaces/SPACE/pages/123",
            DocumentSource.CONFLUENCE,
            "https://example.atlassian.net/wiki/spaces/SPACE/pages/123",
        ),
    ],
)
def test_normalize_url_with_auto_detection(
    url: str, expected_source: DocumentSource, expected_normalized: str
) -> None:
    """Test normalize_url auto-detects source type when source_type not provided."""
    detected = _detect_source_type(url)
    assert detected == expected_source

    normalized = normalize_url(url)  # No source_type provided
    assert normalized == expected_normalized


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://example.com/doc?query=param#section",
            "https://example.com/doc",
        ),
        (
            "https://example.com/doc/",
            "https://example.com/doc",
        ),
        (
            "http://example.com/doc",
            "http://example.com/doc",  # Default normalizer preserves scheme
        ),
    ],
)
def test_default_normalizer(url: str, expected: str) -> None:
    """Test default normalizer for connectors without custom normalizers."""
    # Use a source type that doesn't have a custom normalizer
    result = normalize_url(url, source_type=DocumentSource.WEB)
    assert result == expected


def test_normalize_url_returns_none_for_invalid_url() -> None:
    """Test that normalize_url returns None for invalid URLs."""
    assert normalize_url("not-a-url") is None
    assert normalize_url("") is None


def test_normalize_url_with_unknown_source_type() -> None:
    """Test that normalize_url falls back to default for unknown source types."""
    url = "https://example.com/doc?query=param"
    # Use a source type that doesn't have a custom normalizer
    result = normalize_url(url, source_type=DocumentSource.WEB)
    assert result == "https://example.com/doc"


def test_url_lookup_variants_includes_trailing_slash_versions() -> None:
    """Test that variants include both with and without trailing slash."""
    variants = _url_lookup_variants("https://example.com/path")
    assert "https://example.com/path" in variants
    assert "https://example.com/path/" in variants
    assert len(variants) == 2


def test_url_lookup_variants_strips_query_and_fragment() -> None:
    """Test that variants strip query parameters and fragments."""
    variants = _url_lookup_variants("https://example.com/path?a=1#section")
    assert "https://example.com/path" in variants
    assert "https://example.com/path/" in variants
    # Should not include query/fragment variants
    assert "https://example.com/path?a=1" not in variants
    assert "https://example.com/path#section" not in variants


def test_url_lookup_variants_handles_normalized_urls() -> None:
    """Test that variants work correctly with already-normalized URLs."""
    # Test with a Google Drive URL that's already normalized
    variants = _url_lookup_variants("https://docs.google.com/document/d/abc123def456")
    assert "https://docs.google.com/document/d/abc123def456" in variants
    assert "https://docs.google.com/document/d/abc123def456/" in variants
