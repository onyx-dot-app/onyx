"""Unit tests for Teams bot utility functions."""

from onyx.onyxbot.teams.utils import extract_channel_id
from onyx.onyxbot.teams.utils import extract_team_id
from onyx.onyxbot.teams.utils import extract_team_name
from onyx.onyxbot.teams.utils import is_bot_mentioned
from onyx.onyxbot.teams.utils import strip_bot_mention
from onyx.server.manage.teams_bot.utils import generate_teams_registration_key
from onyx.server.manage.teams_bot.utils import parse_teams_registration_key


class TestExtractIds:
    """Tests for ID extraction from Activity dicts."""

    def test_extract_team_id_present(self, sample_activity_dict: dict) -> None:
        assert extract_team_id(sample_activity_dict) == "team-abc-123"

    def test_extract_team_id_missing(self, sample_dm_activity_dict: dict) -> None:
        assert extract_team_id(sample_dm_activity_dict) is None

    def test_extract_channel_id_present(self, sample_activity_dict: dict) -> None:
        assert extract_channel_id(sample_activity_dict) == "19:channel-xyz@thread.tacv2"

    def test_extract_channel_id_missing(self, sample_dm_activity_dict: dict) -> None:
        assert extract_channel_id(sample_dm_activity_dict) is None

    def test_extract_team_name(self, sample_activity_dict: dict) -> None:
        assert extract_team_name(sample_activity_dict) == "Engineering"

    def test_extract_team_name_missing(self, sample_dm_activity_dict: dict) -> None:
        assert extract_team_name(sample_dm_activity_dict) is None


class TestStripBotMention:
    """Tests for bot mention stripping."""

    def test_strip_named_mention(self) -> None:
        text = "<at>Onyx</at> What is our process?"
        assert strip_bot_mention(text, "Onyx") == "What is our process?"

    def test_strip_case_insensitive(self) -> None:
        text = "<at>onyx</at> Hello"
        assert strip_bot_mention(text, "Onyx") == "Hello"

    def test_strip_no_mention(self) -> None:
        text = "Just a normal message"
        assert strip_bot_mention(text, "Onyx") == "Just a normal message"

    def test_strip_multiple_mentions(self) -> None:
        text = "<at>Onyx</at> hello <at>Onyx</at>"
        assert strip_bot_mention(text, "Onyx") == "hello"

    def test_strip_empty_result(self) -> None:
        text = "<at>Onyx</at>"
        assert strip_bot_mention(text, "Onyx") == ""


class TestIsBotMentioned:
    """Tests for bot mention detection."""

    def test_bot_mentioned(self, sample_activity_dict: dict) -> None:
        assert is_bot_mentioned(sample_activity_dict, "28:bot-id-456") is True

    def test_bot_not_mentioned(self, sample_dm_activity_dict: dict) -> None:
        assert is_bot_mentioned(sample_dm_activity_dict, "28:bot-id-456") is False

    def test_different_bot_mentioned(self, sample_activity_dict: dict) -> None:
        assert is_bot_mentioned(sample_activity_dict, "other-bot-id") is False

    def test_no_entities(self) -> None:
        activity = {"entities": []}
        assert is_bot_mentioned(activity, "any-id") is False


class TestRegistrationKeys:
    """Tests for registration key generation and parsing."""

    def test_generate_and_parse_roundtrip(self) -> None:
        key = generate_teams_registration_key("tenant1")
        parsed = parse_teams_registration_key(key)
        assert parsed == "tenant1"

    def test_generate_has_correct_prefix(self) -> None:
        key = generate_teams_registration_key("tenant1")
        assert key.startswith("teams_")

    def test_parse_invalid_prefix(self) -> None:
        assert parse_teams_registration_key("discord_tenant1.token") is None

    def test_parse_no_separator(self) -> None:
        assert parse_teams_registration_key("teams_noseparator") is None

    def test_parse_empty_string(self) -> None:
        assert parse_teams_registration_key("") is None

    def test_generate_url_encodes_tenant(self) -> None:
        key = generate_teams_registration_key("tenant with spaces")
        parsed = parse_teams_registration_key(key)
        assert parsed == "tenant with spaces"

    def test_generate_unique_keys(self) -> None:
        key1 = generate_teams_registration_key("tenant1")
        key2 = generate_teams_registration_key("tenant1")
        assert key1 != key2
