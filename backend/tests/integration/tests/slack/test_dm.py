"""
Integration tests for Slack Direct Message (DM) functionality.

This module contains tests that verify the behavior of the Onyx Slack bot
when interacting within DMs, covering various configuration options like
responding to bots, showing buttons, filtering messages, standard answers,
and handling tags under different restriction settings.
"""

from typing import Any

import pytest

from onyx.utils.logger import setup_logger
from tests.integration.common_utils.managers.slack import SlackManager
from tests.integration.common_utils.test_models import SlackTestContext
from tests.integration.tests.slack.constants import ANSWER_LENA_BOOKS_STORY
from tests.integration.tests.slack.constants import ANSWER_LENA_BOOKS_WEB
from tests.integration.tests.slack.constants import QUESTION_CAPITAL_FRANCE
from tests.integration.tests.slack.constants import QUESTION_LENA_BOOKS
from tests.integration.tests.slack.constants import QUESTION_LENA_BOOKS_NO_MARK
from tests.integration.tests.slack.constants import QUESTION_LENA_BOOKS_WEB_SOURCE
from tests.integration.tests.slack.constants import QUESTION_NEED_SUPPORT
from tests.integration.tests.slack.constants import SHORT_REPLY_TIMEOUT
from tests.integration.tests.slack.constants import STD_ANSWER_SUPPORT_EMAIL
from tests.integration.tests.slack.slack_test_helpers import assert_button_presence
from tests.integration.tests.slack.slack_test_helpers import send_and_receive_dm
from tests.integration.tests.slack.slack_test_helpers import (
    send_dm_with_optional_timeout,
)
from tests.integration.tests.slack.slack_test_helpers import update_channel_config

logger = setup_logger()

# Note: Messages sent by this test suite are treated as bot messages by Slack.
# Therefore, the 'respond_to_bots' configuration option needs to be enabled
# in most test cases to ensure the bot responds as expected.


@pytest.mark.parametrize(
    "test_name, config_update",
    [
        ("enabled", {"respond_to_bots": False}),
        ("disabled", {"disabled": True}),
    ],
)
def test_dm_default_config(
    slack_test_context: SlackTestContext,
    test_name: str,
    config_update: dict[str, Any] | None,
) -> None:
    """Test cases for Slack DMs using the default configuration."""
    logger.info(f"Testing DM config: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]

    if config_update:
        update_channel_config(bot_id, admin_user, updated_config_data=config_update)

    message = send_and_receive_dm(
        slack_bot_client,
        slack_user_client,
        QUESTION_LENA_BOOKS,
        timeout_secs=SHORT_REPLY_TIMEOUT,
    )
    # Message is treated as bot message so we won't get a response
    assert message is None, f"Bot should not respond when {test_name}"


@pytest.mark.parametrize(
    "test_name, config_update, expected_text",
    [
        (
            "enabled",
            {"respond_to_bots": True},
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
        ("disabled", {"disabled": True, "respond_to_bots": True}, None),
    ],
)
def test_dm_default_config_by_enabling_respond_to_bot(
    slack_test_context: SlackTestContext,
    test_name: str,
    config_update: dict[str, Any],
    expected_text: list[str] | None,
) -> None:
    """
    Test Slack DMs with the 'respond_to_bots' setting enabled.

    Verifies that the bot responds when tagged, even if the message
    originates from a bot.
    """
    logger.info(f"Testing DM config by enabling respond to bot: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]

    if config_update:
        update_channel_config(bot_id, admin_user, updated_config_data=config_update)
    message = send_dm_with_optional_timeout(
        slack_bot_client,
        slack_user_client,
        QUESTION_LENA_BOOKS,
        expected_text=expected_text,
    )
    if expected_text is not None:
        assert message is not None, f"Bot should respond when {test_name}"
        blocks = message["blocks"]
        assert (
            blocks is not None and len(blocks) > 0
        ), f"Response should have blocks when {test_name}"
        assert any(
            text in blocks[0]["text"]["text"] for text in expected_text
        ), f"Response should contain one of '{expected_text}' when {test_name}"
    else:
        assert message is None, f"Bot should not respond when {test_name}"


@pytest.mark.parametrize(
    "test_name, config_update, expect_button, expected_text",
    [
        (
            "continue_in_web_ui_button_enabled",
            {"show_continue_in_web_ui": True, "respond_to_bots": True},
            True,
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
        (
            "continue_in_web_ui_button_disabled",
            {"show_continue_in_web_ui": False, "respond_to_bots": True},
            False,
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
    ],
)
def test_dm_continue_in_web_ui_button(
    slack_test_context: SlackTestContext,
    test_name: str,
    config_update: dict[str, Any],
    expect_button: bool,
    expected_text: list[str],
):
    """Test the presence or absence of the 'Continue in Web UI' button in DM responses based on configuration."""
    logger.info(f"Testing DM continue_in_web_ui button: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]

    update_channel_config(bot_id, admin_user, updated_config_data=config_update)
    message = send_and_receive_dm(
        slack_bot_client,
        slack_user_client,
        QUESTION_LENA_BOOKS,
    )
    assert message is not None, f"{test_name}: Bot should respond"
    blocks = message["blocks"]
    assert (
        blocks is not None and len(blocks) > 0
    ), f"{test_name}: Response should have blocks"
    assert any(
        text in blocks[0]["text"]["text"] for text in expected_text
    ), f"{test_name}: Response should contain one of {expected_text}"
    assert_button_presence(blocks, "continue-in-web-ui", expect_button, test_name)


@pytest.mark.parametrize(
    "test_name, config_update, expect_button, expected_text",
    [
        (
            "follow_up_tags_enabled",
            {"follow_up_tags": ["help@onyx.app"], "respond_to_bots": True},
            True,
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
        (
            "follow_up_tags_disabled",
            {"respond_to_bots": True},
            False,
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
    ],
)
def test_dm_follow_up_button(
    slack_test_context: SlackTestContext,
    test_name: str,
    config_update: dict[str, Any],
    expect_button: bool,
    expected_text: list[str],
):
    """Test the presence or absence of the 'Follow-up' button in DM responses based on configuration."""
    logger.info(f"Testing DM follow_up button: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]

    update_channel_config(bot_id, admin_user, updated_config_data=config_update)
    message = send_and_receive_dm(
        slack_bot_client,
        slack_user_client,
        QUESTION_LENA_BOOKS,
    )
    assert message is not None, f"{test_name}: Bot should respond"
    blocks = message["blocks"]
    assert (
        blocks is not None and len(blocks) > 0
    ), f"{test_name}: Response should have blocks"
    assert any(
        text in blocks[0]["text"]["text"] for text in expected_text
    ), f"{test_name}: Response should contain one of {expected_text}"
    assert_button_presence(blocks, "followup-button", expect_button, test_name)


@pytest.mark.parametrize(
    "test_name, config_update, message_text, expected_text",
    [
        (
            "respond_to_questions_enabled_with_question",
            {"respond_to_bots": True, "answer_filters": ["questionmark_prefilter"]},
            QUESTION_LENA_BOOKS,
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
        (
            "respond_to_questions_enabled_without_question",
            {"respond_to_bots": True, "answer_filters": ["questionmark_prefilter"]},
            QUESTION_LENA_BOOKS_NO_MARK,
            None,
        ),
        (
            "respond_to_questions_enabled_without_question",
            {"respond_to_bots": True},
            QUESTION_LENA_BOOKS_NO_MARK,
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
    ],
)
def test_dm_respond_to_questions(
    slack_test_context: SlackTestContext,
    test_name: str,
    config_update: dict[str, Any],
    message_text: str,
    expected_text: list[str] | None,
):
    """Test the 'respond_to_questions' filter behavior in DMs."""
    logger.info(f"Testing DM respond_to_questions: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]

    update_channel_config(bot_id, admin_user, updated_config_data=config_update)
    message = send_dm_with_optional_timeout(
        slack_bot_client, slack_user_client, message_text, expected_text=expected_text
    )
    if expected_text is None:
        assert message is None, f"{test_name}: Bot should not respond"
    else:
        assert message is not None, f"{test_name}: Bot should respond"
        blocks = message["blocks"]
        assert (
            blocks is not None and len(blocks) > 0
        ), f"{test_name}: Response should have blocks"
        assert any(
            text in blocks[0]["text"]["text"] for text in expected_text
        ), f"{test_name}: Response should contain one of '{expected_text}'"


@pytest.mark.parametrize(
    "test_name, config_update, expected_text",
    [
        (
            "with_standard_answer_category",
            "std_ans_category",  # special marker, handled in test
            STD_ANSWER_SUPPORT_EMAIL,
        ),
        (
            "without_standard_answer_category",
            {"respond_to_bots": True},
            None,  # Should NOT contain standard answer
        ),
    ],
)
def test_dm_standard_answer_category(
    slack_test_context: SlackTestContext,
    test_name: str,
    config_update: dict[str, Any] | str,
    expected_text: Any,
):
    """Test the inclusion of standard answers based on category configuration in DMs."""
    logger.info(f"Testing DM standard answer category: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]

    if config_update == "std_ans_category":
        cat_id = slack_test_context.std_ans_category["id"]
        config = {"respond_to_bots": True, "standard_answer_categories": [cat_id]}
    else:
        config = config_update

    update_channel_config(bot_id, admin_user, updated_config_data=config)
    message = send_and_receive_dm(
        slack_bot_client, slack_user_client, QUESTION_NEED_SUPPORT
    )
    assert message is not None, f"{test_name}: Bot should respond"
    blocks = message["blocks"]
    if expected_text is None:
        assert (
            STD_ANSWER_SUPPORT_EMAIL not in blocks[0]["text"]["text"]
        ), f"{test_name}: Response should NOT contain the standard answer"
    else:
        assert (
            expected_text in blocks[0]["text"]["text"]
        ), f"{test_name}: Response should contain '{expected_text}'"


@pytest.mark.parametrize(
    "test_name, config_update, expected_text",
    [
        (
            "respond_tag_only_enabled",
            {"respond_tag_only": True, "respond_to_bots": True},
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
        (
            "respond_tag_only_disabled",
            {"respond_tag_only": False, "respond_to_bots": True},
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
    ],
)
def test_dm_respond_tag_only(
    slack_test_context: SlackTestContext,
    test_name: str,
    config_update: dict[str, Any],
    expected_text: list[str] | None,
):
    """
    Test the 'respond_tag_only' setting in DMs.

    Note: In DMs, the bot should reply regardless of this setting,
    as tagging is implicit in a direct message context.
    """
    logger.info(f"Testing DM respond_tag_only: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]

    update_channel_config(bot_id, admin_user, updated_config_data=config_update)
    message = send_and_receive_dm(
        slack_bot_client,
        slack_user_client,
        QUESTION_LENA_BOOKS,
    )
    assert message is not None, f"{test_name}: Bot should respond"
    blocks = message["blocks"]
    assert (
        blocks is not None and len(blocks) > 0
    ), f"{test_name}: Response should have blocks"
    assert any(
        text in blocks[0]["text"]["text"] for text in expected_text
    ), f"{test_name}: Response should contain one of '{expected_text}'"


@pytest.mark.parametrize(
    "test_name, config_update, expected_text",
    [
        (
            "respond_to_bots_enabled",
            {"respond_to_bots": True},
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
        ("respond_to_bots_disabled", {"respond_to_bots": False}, None),
    ],
)
def test_dm_respond_to_bots(
    slack_test_context: SlackTestContext,
    test_name: str,
    config_update: dict[str, Any],
    expected_text: list[str] | None,
):
    """
    Test the 'respond_to_bots' setting in DMs.

    Since test messages are treated as bot messages, this directly tests
    whether the bot responds based on this configuration.
    """
    logger.info(f"Testing DM respond_to_bots: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]

    update_channel_config(bot_id, admin_user, updated_config_data=config_update)
    message = send_dm_with_optional_timeout(
        slack_bot_client,
        slack_user_client,
        QUESTION_LENA_BOOKS,
        expected_text,
    )
    if expected_text is None:
        assert message is None, f"{test_name}: Bot should not respond"
    else:
        assert message is not None, f"{test_name}: Bot should respond"
        blocks = message["blocks"]
        assert (
            blocks is not None and len(blocks) > 0
        ), f"{test_name}: Response should have blocks"
        assert any(
            text in blocks[0]["text"]["text"] for text in expected_text
        ), f"{test_name}: Response should contain one of '{expected_text}'"


@pytest.mark.xfail(reason="Citations are not supported in DM")
@pytest.mark.parametrize(
    "test_name, config_update, expected_text",
    [
        (
            "citations_enabled",
            {"respond_to_bots": True, "answer_filters": ["well_answered_postfilter"]},
            "",
        ),
        ("citations_disabled", {"respond_to_bots": True}, None),
    ],
)
def test_dm_citations(
    slack_test_context: SlackTestContext,
    test_name: str,
    config_update: dict[str, Any],
    expected_text: Any,
):
    """Test citation generation in DMs (currently expected to fail)."""
    logger.info(f"Testing DM citations: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]
    update_channel_config(bot_id, admin_user, updated_config_data=config_update)
    message = send_dm_with_optional_timeout(
        slack_bot_client,
        slack_user_client,
        QUESTION_CAPITAL_FRANCE,
        expected_text=expected_text,
    )
    if expected_text is None:
        assert message is None, f"{test_name}: Bot should not respond"
    else:
        assert message is not None, f"{test_name}: Bot should respond"


@pytest.mark.xfail(
    reason="Skipping the test on failure, sometimes we are getting correct response and sometimes not."
)
def test_dm_llm_auto_filters(
    slack_test_context: SlackTestContext,
):
    """Test the behavior of LLM auto filters in DMs."""
    logger.info("Testing DM llm auto filters")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]
    update_channel_config(
        bot_id,
        admin_user,
        updated_config_data={"enable_auto_filters": True, "respond_to_bots": True},
    )

    message = send_and_receive_dm(
        slack_bot_client,
        slack_user_client,
        QUESTION_LENA_BOOKS_WEB_SOURCE,
    )
    assert message is not None, "Bot should respond"
    blocks = message["blocks"]
    assert blocks is not None and len(blocks) > 0, "Response should have blocks"
    assert (
        ANSWER_LENA_BOOKS_WEB in blocks[0]["text"]["text"]
    ), "Response should contain '40'"


@pytest.mark.parametrize(
    "test_name, config_update, expected_text",
    [
        (
            "respond_to_bots_disabled_respond_to_questions_disabled",
            {"respond_to_bots": False},
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
        (
            "respond_to_bots_disabled_respond_to_questions_enabled",
            {"respond_to_bots": False, "answer_filters": ["questionmark_prefilter"]},
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
        (
            "default_config_disabled",
            {"disabled": True},
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
    ],
)
def test_dm_tag_with_restriction(
    slack_test_context: SlackTestContext,
    test_name: str,
    config_update: dict[str, Any],
    expected_text: list[str] | None,
):
    """
    Verify that the bot responds to a direct tag in DMs even when restrictive settings are enabled.

    Tests scenarios where 'respond_to_bots' is disabled, 'respond_to_questions'
    is enabled (but the message isn't a question), or the overall configuration is disabled.
    Tagging the bot should override these restrictions in DMs.
    """
    logger.info(f"Testing DM respond_to_bots with restrictions: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]

    update_channel_config(bot_id, admin_user, updated_config_data=config_update)

    user_id, _ = SlackManager.get_client_user_and_bot_ids(
        slack_test_context.slack_bot_client
    )
    logger.info(f"Slack bot user ID: {user_id}")

    # tag the bot in the message
    message = f"<@{user_id}> {QUESTION_LENA_BOOKS_NO_MARK}"
    logger.info(f"Sending message to bot: {message}")

    message = send_and_receive_dm(slack_bot_client, slack_user_client, message)
    assert message is not None, f"{test_name}: Bot should respond"
    blocks = message["blocks"]
    assert (
        blocks is not None and len(blocks) > 0
    ), f"{test_name}: Response should have blocks"
    assert any(
        text in blocks[0]["text"]["text"] for text in expected_text
    ), f"{test_name}: Response should contain one of '{expected_text}'"
