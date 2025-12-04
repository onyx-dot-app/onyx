from unittest.mock import MagicMock

from onyx.context.search.federated.slack_search_utils import (
    build_channel_query_filter,
)
from onyx.context.search.federated.slack_search_utils import matches_exclude_pattern
from onyx.onyxbot.slack.models import ChannelType


class TestChannelPatternMatching:
    """Test glob pattern matching for channel exclusion"""

    def test_exact_match(self) -> None:
        """Test exact channel name match"""
        assert matches_exclude_pattern("customer-support", ["customer-support"]) is True
        assert matches_exclude_pattern("engineering", ["customer-support"]) is False

    def test_glob_pattern_star(self) -> None:
        """Test glob patterns with * wildcard"""
        # Suffix wildcard
        assert matches_exclude_pattern("customer-X", ["customer*"]) is True
        assert matches_exclude_pattern("customer-support", ["customer*"]) is True
        assert matches_exclude_pattern("engineering", ["customer*"]) is False

        # Prefix wildcard
        assert matches_exclude_pattern("test-env", ["*-env"]) is True
        assert matches_exclude_pattern("prod-env", ["*-env"]) is True
        assert matches_exclude_pattern("test-staging", ["*-env"]) is False

        # Infix wildcard
        assert matches_exclude_pattern("customer-test-env", ["customer*env"]) is True
        assert matches_exclude_pattern("customer-prod-env", ["customer*env"]) is True
        assert matches_exclude_pattern("customer-test", ["customer*env"]) is False

    def test_multiple_patterns(self) -> None:
        """Test matching against multiple patterns"""
        patterns = ["test-*", "dev-*", "customer*"]

        assert matches_exclude_pattern("test-env", patterns) is True
        assert matches_exclude_pattern("dev-env", patterns) is True
        assert matches_exclude_pattern("customer-X", patterns) is True
        assert matches_exclude_pattern("prod-env", patterns) is False

    def test_hash_prefix_normalization(self) -> None:
        """Test that # prefix is handled correctly"""
        # Pattern has #, channel name doesn't
        assert matches_exclude_pattern("customer-X", ["#customer*"]) is True

        # Channel name has #, pattern doesn't
        assert matches_exclude_pattern("#customer-X", ["customer*"]) is True

        # Both have #
        assert matches_exclude_pattern("#customer-X", ["#customer*"]) is True

    def test_case_insensitive(self) -> None:
        """Test that matching is case insensitive"""
        assert matches_exclude_pattern("Customer-Support", ["customer*"]) is True
        assert matches_exclude_pattern("CUSTOMER-X", ["customer*"]) is True
        assert matches_exclude_pattern("customer-x", ["CUSTOMER*"]) is True

    def test_whitespace_handling(self) -> None:
        """Test that whitespace is trimmed"""
        assert matches_exclude_pattern(" customer-X ", ["customer*"]) is True
        assert matches_exclude_pattern("customer-X", [" customer* "]) is True


class TestChannelQueryFilterBuilding:
    """Test channel query filter string construction"""

    def test_specific_channels_no_exclude(self) -> None:
        """Test filter with specific channels, no exclusions"""
        entities = {
            "search_all_channels": False,
            "channels": ["general", "engineering"],
        }

        filter_str = build_channel_query_filter(entities)

        assert "in:#general" in filter_str
        assert "in:#engineering" in filter_str
        assert filter_str.count("in:#") == 2

    def test_specific_channels_with_exclude(self) -> None:
        """Test filter with specific channels and exclusions"""
        entities = {
            "search_all_channels": False,
            "channels": ["general", "customer-X", "customer-Y", "support"],
            "exclude_channels": ["customer*"],
        }

        filter_str = build_channel_query_filter(entities)

        # Should include non-customer channels
        assert "in:#general" in filter_str
        assert "in:#support" in filter_str

        # Should exclude customer channels
        assert "customer-X" not in filter_str
        assert "customer-Y" not in filter_str

    def test_all_channels_no_exclude(self) -> None:
        """Test search all channels with no exclusions"""
        entities = {"search_all_channels": True}

        filter_str = build_channel_query_filter(entities)

        # Should return empty string (no filter)
        assert filter_str == ""

    def test_all_channels_with_exclude(self) -> None:
        """Test search all channels with exclusions"""
        entities = {
            "search_all_channels": True,
            "exclude_channels": ["customer*", "test-*"],
        }
        available_channels = [
            "general",
            "customer-X",
            "customer-Y",
            "test-env",
            "support",
        ]

        filter_str = build_channel_query_filter(entities, available_channels)

        # Should use negative filters for excluded channels
        assert "-in:#customer-X" in filter_str
        assert "-in:#customer-Y" in filter_str
        assert "-in:#test-env" in filter_str

        # Should NOT include positive filters (we're searching ALL channels, just excluding some)
        assert "in:#general" not in filter_str
        assert "in:#support" not in filter_str

    def test_empty_channels_list(self) -> None:
        """Test with empty channels list"""
        entities = {"search_all_channels": False, "channels": []}

        # Should raise ValidationError during entity parsing, but if it gets through
        # should return empty string
        try:
            filter_str = build_channel_query_filter(entities)
            assert filter_str == ""
        except Exception:
            # Expected - validation should fail
            pass

    def test_channel_name_normalization(self) -> None:
        """Test that channel names are normalized (# removed)"""
        entities = {
            "search_all_channels": False,
            "channels": ["#general", "engineering"],  # One with #, one without
        }

        filter_str = build_channel_query_filter(entities)

        # Both should be included with in:# prefix
        assert "in:#general" in filter_str
        assert "in:#engineering" in filter_str

    def test_invalid_entities(self) -> None:
        """Test with invalid entities"""
        entities = {"invalid_field": "value"}

        filter_str = build_channel_query_filter(entities)

        # Should return empty string on validation error
        assert filter_str == ""

    def test_no_available_channels(self) -> None:
        """Test exclude patterns when channel list fetch fails"""
        entities = {
            "search_all_channels": True,
            "exclude_channels": ["customer*"],
        }
        available_channels = None  # Channel fetch failed

        filter_str = build_channel_query_filter(entities, available_channels)

        # Should return empty string if we can't fetch channels
        assert filter_str == ""


class TestDateExtraction:
    """Test date range extraction from queries"""

    def test_extract_explicit_days(self) -> None:
        """Test extracting explicit day ranges"""
        from onyx.context.search.federated.slack_search_utils import (
            extract_date_range_from_query,
        )

        mock_llm = MagicMock()

        # Mock LLM response for "last 7 days"
        mock_llm.invoke.return_value = MagicMock()
        mock_llm.invoke.return_value.content = '{"days_back": 7}'

        days = extract_date_range_from_query(
            "show me results from last 7 days", mock_llm, 30
        )

        assert days == 7

    def test_enforce_default_search_days_limit(self) -> None:
        """Test that default_search_days is enforced as hard limit"""
        from onyx.context.search.federated.slack_search_utils import (
            extract_date_range_from_query,
        )

        mock_llm = MagicMock()

        # Mock LLM response for "last 90 days" but limit is 30
        mock_llm.invoke.return_value = MagicMock()
        mock_llm.invoke.return_value.content = '{"days_back": 90}'

        days = extract_date_range_from_query(
            "show me results from last 90 days", mock_llm, 30
        )

        # Should be capped at 30
        assert days == 30

    def test_no_date_mentioned(self) -> None:
        """Test when no date is mentioned in query"""
        from onyx.context.search.federated.slack_search_utils import (
            extract_date_range_from_query,
        )

        mock_llm = MagicMock()

        # Mock LLM response for no date
        mock_llm.invoke.return_value = MagicMock()
        mock_llm.invoke.return_value.content = '{"days_back": null}'

        days = extract_date_range_from_query("show me budget reports", mock_llm, 30)

        # Should use default
        assert days == 30

    def test_llm_failure_fallback(self) -> None:
        """Test fallback when LLM fails"""
        from onyx.context.search.federated.slack_search_utils import (
            extract_date_range_from_query,
        )

        mock_llm = MagicMock()

        # Mock LLM failure
        mock_llm.invoke.side_effect = Exception("LLM error")

        days = extract_date_range_from_query("show me results", mock_llm, 30)

        # Should fall back to default
        assert days == 30


class TestChannelTypeFiltering:
    """Test post-filtering based on channel type"""

    def test_include_public_channels_always(self) -> None:
        """Test that public channels are always included"""
        from onyx.context.search.federated.slack_search_utils import (
            should_include_message,
        )

        entities = {
            "include_dm": False,
            "include_private_channels": False,
        }

        assert should_include_message(ChannelType.PUBLIC_CHANNEL, entities) is True

    def test_filter_dm_based_on_entities(self) -> None:
        """Test DM filtering based on include_dm setting"""
        from onyx.context.search.federated.slack_search_utils import (
            should_include_message,
        )

        # DMs enabled
        entities_with_dm = {"include_dm": True}
        assert should_include_message(ChannelType.IM, entities_with_dm) is True

        # DMs disabled
        entities_no_dm = {"include_dm": False}
        assert should_include_message(ChannelType.IM, entities_no_dm) is False

    def test_filter_group_dm(self) -> None:
        """Test group DM (MPIM) filtering uses include_group_dm setting"""
        from onyx.context.search.federated.slack_search_utils import (
            should_include_message,
        )

        # Group DMs should follow include_group_dm setting
        entities_with_group_dm = {"include_group_dm": True}
        assert should_include_message(ChannelType.MPIM, entities_with_group_dm) is True

        entities_no_group_dm = {"include_group_dm": False}
        assert should_include_message(ChannelType.MPIM, entities_no_group_dm) is False

    def test_filter_private_channels(self) -> None:
        """Test private channel filtering"""
        from onyx.context.search.federated.slack_search_utils import (
            should_include_message,
        )

        # Private channels enabled
        entities_with_private = {"include_private_channels": True}
        assert (
            should_include_message(ChannelType.PRIVATE_CHANNEL, entities_with_private)
            is True
        )

        # Private channels disabled
        entities_no_private = {"include_private_channels": False}
        assert (
            should_include_message(ChannelType.PRIVATE_CHANNEL, entities_no_private)
            is False
        )

    def test_invalid_entities_default_behavior(self) -> None:
        """Test that invalid entities default to including messages"""
        from onyx.context.search.federated.slack_search_utils import (
            should_include_message,
        )

        invalid_entities = {"invalid_field": "value"}

        # Should default to including (safe behavior)
        assert (
            should_include_message(ChannelType.PUBLIC_CHANNEL, invalid_entities) is True
        )
