"""Tests for Slack channel reference resolution and tag filtering
in handle_regular_answer.py."""

from unittest.mock import MagicMock

from slack_sdk.errors import SlackApiError

from onyx.context.search.models import Tag
from onyx.onyxbot.slack.constants import SLACK_CHANNEL_REF_PATTERN
from onyx.onyxbot.slack.handlers.handle_regular_answer import resolve_channel_references


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client_with_channels(
    channel_map: dict[str, str],
) -> MagicMock:
    """Return a mock WebClient where conversations_info resolves IDs to names."""
    client = MagicMock()

    def _conversations_info(channel: str) -> MagicMock:
        if channel in channel_map:
            resp = MagicMock()
            resp.validate = MagicMock()
            resp.__getitem__ = lambda _self, key: {
                "channel": {
                    "name": channel_map[channel],
                    "is_im": False,
                    "is_mpim": False,
                }
            }[key]
            return resp
        raise SlackApiError("channel_not_found", response=MagicMock())

    client.conversations_info = _conversations_info
    return client


def _mock_logger() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# SLACK_CHANNEL_REF_PATTERN regex tests
# ---------------------------------------------------------------------------


class TestSlackChannelRefPattern:
    def test_matches_bare_channel_id(self) -> None:
        matches = SLACK_CHANNEL_REF_PATTERN.findall("<#C097NBWMY8Y>")
        assert matches == [("C097NBWMY8Y", "")]

    def test_matches_channel_id_with_name(self) -> None:
        matches = SLACK_CHANNEL_REF_PATTERN.findall("<#C097NBWMY8Y|eng-infra>")
        assert matches == [("C097NBWMY8Y", "eng-infra")]

    def test_matches_multiple_channels(self) -> None:
        msg = "compare <#C111AAA> and <#C222BBB|general>"
        matches = SLACK_CHANNEL_REF_PATTERN.findall(msg)
        assert len(matches) == 2
        assert ("C111AAA", "") in matches
        assert ("C222BBB", "general") in matches

    def test_no_match_on_plain_text(self) -> None:
        matches = SLACK_CHANNEL_REF_PATTERN.findall("no channels here")
        assert matches == []

    def test_no_match_on_user_mention(self) -> None:
        matches = SLACK_CHANNEL_REF_PATTERN.findall("<@U12345>")
        assert matches == []


# ---------------------------------------------------------------------------
# resolve_channel_references tests
# ---------------------------------------------------------------------------


class TestResolveChannelReferences:
    def test_resolves_bare_channel_id_via_api(self) -> None:
        client = _mock_client_with_channels({"C097NBWMY8Y": "eng-infra"})
        logger = _mock_logger()

        message, tags = resolve_channel_references(
            message="summary of <#C097NBWMY8Y> this week",
            client=client,
            logger=logger,
        )

        assert message == "summary of #eng-infra this week"
        assert len(tags) == 1
        assert tags[0] == Tag(tag_key="Channel", tag_value="eng-infra")

    def test_uses_name_from_pipe_format_without_api_call(self) -> None:
        client = MagicMock()
        logger = _mock_logger()

        message, tags = resolve_channel_references(
            message="check <#C097NBWMY8Y|eng-infra> for updates",
            client=client,
            logger=logger,
        )

        assert message == "check #eng-infra for updates"
        assert tags == [Tag(tag_key="Channel", tag_value="eng-infra")]
        # Should NOT have called the API since name was in the markup
        client.conversations_info.assert_not_called()

    def test_multiple_channels(self) -> None:
        client = _mock_client_with_channels(
            {
                "C111AAA": "eng-infra",
                "C222BBB": "eng-general",
            }
        )
        logger = _mock_logger()

        message, tags = resolve_channel_references(
            message="compare <#C111AAA> and <#C222BBB>",
            client=client,
            logger=logger,
        )

        assert "#eng-infra" in message
        assert "#eng-general" in message
        assert "<#" not in message
        assert len(tags) == 2
        tag_values = {t.tag_value for t in tags}
        assert tag_values == {"eng-infra", "eng-general"}

    def test_no_channel_references_returns_unchanged(self) -> None:
        client = MagicMock()
        logger = _mock_logger()

        message, tags = resolve_channel_references(
            message="just a normal message with no channels",
            client=client,
            logger=logger,
        )

        assert message == "just a normal message with no channels"
        assert tags == []

    def test_api_failure_skips_channel_gracefully(self) -> None:
        # Client that fails for all channel lookups
        client = _mock_client_with_channels({})
        logger = _mock_logger()

        message, tags = resolve_channel_references(
            message="check <#CBADID123>",
            client=client,
            logger=logger,
        )

        # Message should remain unchanged for the failed channel
        assert "<#CBADID123>" in message
        assert tags == []
        logger.warning.assert_called_once()

    def test_partial_failure_resolves_what_it_can(self) -> None:
        # Only one of two channels resolves
        client = _mock_client_with_channels({"C111AAA": "eng-infra"})
        logger = _mock_logger()

        message, tags = resolve_channel_references(
            message="compare <#C111AAA> and <#CBADID123>",
            client=client,
            logger=logger,
        )

        assert "#eng-infra" in message
        assert "<#CBADID123>" in message  # failed one stays raw
        assert len(tags) == 1
        assert tags[0].tag_value == "eng-infra"

    def test_duplicate_channel_produces_single_tag(self) -> None:
        client = _mock_client_with_channels({"C111AAA": "eng-infra"})
        logger = _mock_logger()

        message, tags = resolve_channel_references(
            message="summarize <#C111AAA> and compare with <#C111AAA>",
            client=client,
            logger=logger,
        )

        assert message == "summarize #eng-infra and compare with #eng-infra"
        assert len(tags) == 1
        assert tags[0].tag_value == "eng-infra"

    def test_mixed_pipe_and_bare_formats(self) -> None:
        client = _mock_client_with_channels({"C222BBB": "random"})
        logger = _mock_logger()

        message, tags = resolve_channel_references(
            message="see <#C111AAA|eng-infra> and <#C222BBB>",
            client=client,
            logger=logger,
        )

        assert "#eng-infra" in message
        assert "#random" in message
        assert len(tags) == 2
