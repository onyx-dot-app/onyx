import pytest

from onyx.connectors.coda.helpers.parser import CodaParser
from tests.unit.onyx.connectors.coda.conftest import make_doc
from tests.unit.onyx.connectors.coda.conftest import make_page


@pytest.fixture(scope="module")
def parser() -> CodaParser:
    """Coda Parser."""
    parser = CodaParser()
    return parser


class TestParseTimestamp:
    # ========================================================================
    # Valid Timestamp Tests
    # ========================================================================

    def test_parse_timestamp_with_milliseconds(self, parser: CodaParser):
        """Test parsing ISO 8601 timestamp with milliseconds and Z suffix."""
        result = parser.parse_timestamp("2025-12-09T19:47:48.000Z")
        assert result == pytest.approx(1765309668.0, abs=1.0)

    def test_parse_timestamp_without_milliseconds(self, parser: CodaParser):
        """Test parsing ISO 8601 timestamp without milliseconds."""
        result = parser.parse_timestamp("2025-12-09T19:47:48Z")
        assert result == pytest.approx(1765309668.0, abs=1.0)

    def test_parse_timestamp_with_timezone_offset(self, parser: CodaParser):
        """Test parsing timestamp with timezone offset (+00:00 format)."""
        result = parser.parse_timestamp("2025-12-09T19:47:48+00:00")
        assert result == pytest.approx(1765309668.0, abs=1.0)

    def test_parse_timestamp_with_different_timezone(self, parser: CodaParser):
        """Test parsing timestamp with non-UTC timezone (should convert to UTC)."""
        # 19:47:48 UTC = 14:47:48 EST (UTC-5)
        result = parser.parse_timestamp("2025-12-09T14:47:48-05:00")
        assert result == pytest.approx(1765309668.0, abs=1.0)

    def test_parse_timestamp_naive_datetime(self, parser: CodaParser):
        """Test parsing naive datetime (no timezone info) - should assume UTC."""
        result = parser.parse_timestamp("2025-12-09T19:47:48")
        assert result == pytest.approx(1765309668.0, abs=1.0)

    def test_parse_timestamp_microseconds(self, parser: CodaParser):
        """Test parsing timestamp with microseconds precision."""
        result = parser.parse_timestamp("2025-12-09T19:47:48.123456Z")
        assert result == pytest.approx(1765309668.123456, abs=0.001)

    # ========================================================================
    # Invalid Timestamp Tests
    # ========================================================================

    def test_parse_timestamp_empty_string(self, parser: CodaParser):
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError, match="expected non-empty string"):
            parser.parse_timestamp("")

    def test_parse_timestamp_invalid_format(self, parser: CodaParser):
        """Test that invalid format raises ValueError with helpful message."""
        with pytest.raises(ValueError, match="Invalid timestamp format"):
            parser.parse_timestamp("invalid")

    def test_parse_timestamp_wrong_type_none(self, parser: CodaParser):
        """Test that None raises ValueError."""
        with pytest.raises(ValueError, match="expected non-empty string"):
            parser.parse_timestamp(None)

    def test_parse_timestamp_wrong_type_int(self, parser: CodaParser):
        """Test that integer raises ValueError."""
        with pytest.raises(ValueError, match="expected non-empty string"):
            parser.parse_timestamp(1765309668)

    def test_parse_timestamp_malformed_date(self, parser: CodaParser):
        """Test that malformed date raises ValueError."""
        with pytest.raises(ValueError, match="Invalid timestamp format"):
            parser.parse_timestamp("2025-13-40T25:61:61Z")  # Invalid month, day, hour


class TestBuildSemanticIdentifier:
    """Comprehensive tests for build_semantic_identifier method."""

    # ========================================================================
    # Basic Functionality Tests
    # ========================================================================

    def test_page_with_name_only(self):
        """Test title for page with only a name."""
        page = make_page(id="p1", name="Getting Started")
        result = CodaParser.build_semantic_identifier(page)
        assert result == "Getting Started"

    def test_page_with_name_and_subtitle(self):
        """Test title for page with both name and subtitle."""
        page = make_page(id="p1", name="Guide", subtitle="Introduction")
        result = CodaParser.build_semantic_identifier(page)
        assert result == "Guide / Introduction"

    def test_page_with_empty_name(self):
        """Test title for page with empty string name."""
        page = make_page(id="p1", name="")
        result = CodaParser.build_semantic_identifier(page)
        assert result == "Untitled Page (p1)"

    def test_page_with_subtitle_but_no_name(self):
        """Test that subtitle is not used if name is missing."""
        page = make_page(id="p1", name="", subtitle="Just a subtitle")
        result = CodaParser.build_semantic_identifier(page)
        assert result == "Untitled Page (p1) / Just a subtitle"

    def test_custom_separator(self):
        """Test title with custom separator."""
        page = make_page(id="p1", name="", subtitle="Introduction")
        result = CodaParser.build_semantic_identifier(page, separator=" | ")
        assert result == "Untitled Page (p1) | Introduction"

    # ========================================================================
    # Whitespace Handling Tests
    # ========================================================================

    def test_name_with_leading_trailing_whitespace(self):
        """Test that whitespace is not preserved."""
        page = make_page(id="p1", name="  Guide  ")
        result = CodaParser.build_semantic_identifier(page)
        assert result == "Guide"

    def test_whitespace_only_name(self):
        """Test that whitespace-only name uses fallback."""
        page = make_page(id="p1", name="   ")
        result = CodaParser.build_semantic_identifier(page)
        assert result == "Untitled Page (p1)"

    def test_subtitle_with_whitespace_sanitized(self):
        """Test that subtitle whitespace is stripped when sanitized."""
        page = make_page(id="p1", name="Guide", subtitle="  Introduction  ")
        result = CodaParser.build_semantic_identifier(page)
        assert result == "Guide / Introduction"

    def test_empty_subtitle_after_stripping(self):
        """Test that whitespace-only subtitle is ignored."""
        page = make_page(id="p1", name="Guide", subtitle="   ")
        result = CodaParser.build_semantic_identifier(page)
        assert result == "Guide"

    # ========================================================================
    # Length Limiting Tests
    # ========================================================================

    def test_title_within_max_length(self):
        """Test that titles within limit are unchanged."""
        page = make_page(id="p1", name="Short Title")
        result = CodaParser.build_semantic_identifier(page, max_length=50)
        assert result == "Short Title"

    def test_title_exceeds_max_length(self):
        """Test that long titles are truncated."""
        page = make_page(id="p1", name="A" * 100)
        result = CodaParser.build_semantic_identifier(page, max_length=50)
        assert len(result) == 50
        assert result.endswith("...")
        assert result == "A" * 47 + "..."

    def test_title_with_subtitle_exceeds_max_length(self):
        """Test truncation with name and subtitle."""
        page = make_page(id="p1", name="A" * 50, subtitle="B" * 50)
        result = CodaParser.build_semantic_identifier(page, max_length=50)
        assert len(result) == 50
        assert result.endswith("...")

    def test_max_length_exactly_at_limit(self):
        """Test title that is exactly at max length."""
        page = make_page(id="p1", name="X" * 50)
        result = CodaParser.build_semantic_identifier(page, max_length=50)
        assert result == "X" * 50
        assert not result.endswith("...")


class TestCreatePageKey:
    # ========================================================================
    # Basic Functionality Tests
    # ========================================================================
    def test_create_page_key(self):
        """Test that create_page_key returns expected format."""
        page = make_page()
        doc = make_doc()
        result = CodaParser.create_page_key(doc.id, page.id)
        assert result == f"{doc.id}:page:{page.id}"
