"""Integration tests for Slack channel configurations and bot interactions.

This suite verifies the behavior of the Slack bot based on various channel-specific
and default configuration settings, including message filtering, response conditions,
button visibility, standard answers, user restrictions, and ephemeral messaging.
"""

import time
from typing import Any

import pytest

from onyx.db.engine import get_session_context_manager
from onyx.utils.logger import setup_logger
from tests.integration.common_utils.managers.slack import SlackManager
from tests.integration.common_utils.test_models import SlackTestContext
from tests.integration.tests.slack.constants import ANSWER_LENA_BOOKS_STORY
from tests.integration.tests.slack.constants import ANSWER_LENA_BOOKS_WEB
from tests.integration.tests.slack.constants import DEFAULT_REPLY_TIMEOUT
from tests.integration.tests.slack.constants import EPHEMERAL_MESSAGE_ANSWER
from tests.integration.tests.slack.constants import EPHEMERAL_MESSAGE_QUESTION
from tests.integration.tests.slack.constants import QUESTION_CAPITAL_FRANCE
from tests.integration.tests.slack.constants import QUESTION_LENA_BOOKS
from tests.integration.tests.slack.constants import QUESTION_LENA_BOOKS_NO_MARK
from tests.integration.tests.slack.constants import QUESTION_LENA_BOOKS_WEB_SOURCE
from tests.integration.tests.slack.constants import QUESTION_NEED_SUPPORT
from tests.integration.tests.slack.constants import SHORT_REPLY_TIMEOUT
from tests.integration.tests.slack.constants import SLEEP_BEFORE_EPHEMERAL_CHECK
from tests.integration.tests.slack.constants import STD_ANSWER_SUPPORT_EMAIL
from tests.integration.tests.slack.slack_test_helpers import assert_button_presence
from tests.integration.tests.slack.slack_test_helpers import (
    get_last_chat_session_and_messages,
)
from tests.integration.tests.slack.slack_test_helpers import get_primary_user_record
from tests.integration.tests.slack.slack_test_helpers import (
    send_and_receive_channel_message,
)
from tests.integration.tests.slack.slack_test_helpers import (
    send_channel_msg_with_optional_timeout,
)
from tests.integration.tests.slack.slack_test_helpers import send_message_to_channel
from tests.integration.tests.slack.slack_test_helpers import update_channel_config

logger = setup_logger()
# Note: Messages sent by this test suite are treated as bot messages by Slack.
# Therefore, the 'respond_to_bots' configuration option needs to be enabled
# in most test cases to ensure the bot responds as expected.


@pytest.mark.parametrize(
    "test_name, channel_1_config, channel_2_config, expected_text_channel_1, expected_text_channel_2",
    [
        (
            "enabled_in_both",
            {"respond_to_bots": False, "respond_tag_only": False, "disabled": False},
            {"respond_to_bots": False, "respond_tag_only": False, "disabled": False},
            None,
            None,
        ),
        (
            "disabled_in_both",
            {"respond_to_bots": False, "respond_tag_only": False, "disabled": True},
            {"respond_to_bots": False, "respond_tag_only": False, "disabled": True},
            None,
            None,
        ),
    ],
)
def test_default_config_and_channel_config(
    slack_test_context: SlackTestContext,
    test_name: str,
    channel_1_config: dict[str, Any],
    channel_2_config: dict[str, Any],
    expected_text_channel_1: list[str] | None,
    expected_text_channel_2: list[str] | None,
) -> None:
    """Verify that the bot does not respond in channels when both default
    and channel-specific configurations are disabled and enabled because the message
    is sent by the test suite is considered as a bot message."""
    logger.info(f"Running test: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    test_channel_1 = slack_test_context.test_channel_1
    test_channel_2 = slack_test_context.test_channel_2
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]

    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        channel_name=test_channel_1["name"],
        updated_config_data=channel_1_config,
    )
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        updated_config_data=channel_2_config,
    )

    for channel in [test_channel_1, test_channel_2]:
        message = send_channel_msg_with_optional_timeout(
            slack_bot_client=slack_bot_client,
            slack_user_client=slack_user_client,
            message_text=QUESTION_LENA_BOOKS,
            channel=channel,
            expected_text=(
                expected_text_channel_1
                if channel == test_channel_1
                else expected_text_channel_2
            ),
        )
        assert (
            message is None
        ), f"{test_name}: Bot should not respond in {channel['name']}"


@pytest.mark.parametrize(
    "test_name, channel_1_config, channel_2_config, expect_button_channel_1, expect_button_channel_2, expected_text",
    [
        (
            "enabled_in_both",
            {"show_continue_in_web_ui": True, "respond_to_bots": True},
            {"show_continue_in_web_ui": True, "respond_to_bots": True},
            True,
            True,
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
        (
            "enabled_in_channel_1_only",
            {"show_continue_in_web_ui": True, "respond_to_bots": True},
            {"show_continue_in_web_ui": False, "respond_to_bots": True},
            True,
            False,
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
        (
            "disabled_in_both",
            {"show_continue_in_web_ui": False, "respond_to_bots": True},
            {"show_continue_in_web_ui": False, "respond_to_bots": True},
            False,
            False,
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
    ],
)
def test_show_continue_in_web_ui_button(
    slack_test_context: SlackTestContext,
    test_name: str,
    channel_1_config: dict[str, Any],
    channel_2_config: dict[str, Any],
    expect_button_channel_1: bool,
    expect_button_channel_2: bool,
    expected_text: list[str],
):
    """Verify the presence or absence of the 'Continue in Web UI' button based on channel configurations."""
    logger.info(f"Running test: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]
    test_channel_1 = slack_test_context.test_channel_1
    test_channel_2 = slack_test_context.test_channel_2

    # Update channel 1 config
    logger.info(f"test_channel_1 : {test_channel_1}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        channel_name=test_channel_1["name"],
        updated_config_data=channel_1_config,
    )
    # Update default config (applies to channel 2)
    logger.info(f"Channel 2 config: {channel_2_config}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        updated_config_data=channel_2_config,
    )

    for channel, expect_button, channel_name in [
        (test_channel_1, expect_button_channel_1, "test_channel_1"),
        (test_channel_2, expect_button_channel_2, "test_channel_2"),
    ]:
        message = send_and_receive_channel_message(
            slack_user_client=slack_user_client,
            slack_bot_client=slack_bot_client,
            message=QUESTION_LENA_BOOKS,
            channel=channel,
            tag_bot=True,
        )
        assert message is not None, f"{test_name}: Bot should respond in {channel_name}"
        blocks = message["blocks"]
        assert (
            blocks is not None and len(blocks) > 0
        ), f"{test_name}: Response should have blocks in {channel_name}"
        assert any(
            text in blocks[0]["text"]["text"] for text in expected_text
        ), f"{test_name}: Response should contain one of '{expected_text}'"
        assert_button_presence(
            blocks, "continue-in-web-ui", expect_button, test_name, channel_name
        )


@pytest.mark.parametrize(
    "test_name, channel_1_config, channel_2_config, expected_text_channel_1, expected_text_channel_2",
    [
        (
            "enabled_in_both",
            {"respond_to_bots": True, "respond_tag_only": False},
            {"respond_to_bots": True, "respond_tag_only": False},
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
        (
            "enabled_in_channel_1_only",
            {"respond_to_bots": True, "respond_tag_only": False},
            {"respond_to_bots": False, "respond_tag_only": False},
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
            None,
        ),
        (
            "disabled_in_both",
            {"respond_to_bots": False, "respond_tag_only": False},
            {"respond_to_bots": False, "respond_tag_only": False},
            None,
            None,
        ),
    ],
)
def test_respond_to_bot(
    slack_test_context: SlackTestContext,
    test_name: str,
    channel_1_config: dict[str, Any],
    channel_2_config: dict[str, Any],
    expected_text_channel_1: list[str] | None,
    expected_text_channel_2: list[str] | None,
):
    """Verify the 'respond to bots' setting in channels.

    Messages sent by the test suite are treated as bot messages.
    """
    logger.info(f"Running test: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]
    test_channel_1 = slack_test_context.test_channel_1
    test_channel_2 = slack_test_context.test_channel_2

    # Update channel 1 config
    logger.info(f"test_channel_1 : {test_channel_1}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        channel_name=test_channel_1["name"],
        updated_config_data=channel_1_config,
    )
    # Update default config (applies to channel 2)
    logger.info(f"Channel 2 config: {channel_2_config}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        updated_config_data=channel_2_config,
    )

    for channel, expected_text, channel_name in [
        (test_channel_1, expected_text_channel_1, "test_channel_1"),
        (test_channel_2, expected_text_channel_2, "test_channel_2"),
    ]:
        message = send_channel_msg_with_optional_timeout(
            slack_bot_client=slack_bot_client,
            slack_user_client=slack_user_client,
            message_text=QUESTION_LENA_BOOKS,
            channel=channel,
            expected_text=expected_text,
        )
        if expected_text is None:
            assert (
                message is None
            ), f"{test_name}: Bot should not respond in {channel_name}"
            continue
        assert message is not None, f"{test_name}: Bot should respond in {channel_name}"
        blocks = message["blocks"]
        assert (
            blocks is not None and len(blocks) > 0
        ), f"{test_name}: Response should have blocks in {channel_name}"
        assert any(
            text in blocks[0]["text"]["text"] for text in expected_text
        ), f"{test_name}: Response should contain one of '{expected_text}'"


@pytest.mark.parametrize(
    "test_name, channel_1_config, channel_2_config, expect_button_channel_1, expect_button_channel_2",
    [
        (
            "enabled_in_both",
            {"follow_up_tags": ["help@onyx.app"], "respond_to_bots": True},
            {"follow_up_tags": ["help@onyx.app"], "respond_to_bots": True},
            True,
            True,
        ),
        (
            "enabled_in_channel_1_only",
            {"follow_up_tags": ["help@onyx.app"], "respond_to_bots": True},
            {"respond_to_bots": True},
            True,
            False,
        ),
        (
            "disabled_in_both",
            {"respond_to_bots": True},
            {"respond_to_bots": True},
            False,
            False,
        ),
    ],
)
def test_follow_up_tags(
    slack_test_context: SlackTestContext,
    test_name: str,
    channel_1_config: dict[str, Any],
    channel_2_config: dict[str, Any],
    expect_button_channel_1: bool,
    expect_button_channel_2: bool,
):
    """Verify the presence or absence of the follow-up button based on channel configurations."""
    logger.info(f"Running test: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]
    test_channel_1 = slack_test_context.test_channel_1
    test_channel_2 = slack_test_context.test_channel_2

    # Update channel 1 config
    logger.info(f"test_channel_1 : {test_channel_1}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        channel_name=test_channel_1["name"],
        updated_config_data=channel_1_config,
    )
    # Update default config (applies to channel 2)
    logger.info(f"Channel 2 config: {channel_2_config}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        updated_config_data=channel_2_config,
    )

    for channel, expect_button, channel_name in [
        (test_channel_1, expect_button_channel_1, "test_channel_1"),
        (test_channel_2, expect_button_channel_2, "test_channel_2"),
    ]:
        message = send_and_receive_channel_message(
            slack_user_client=slack_user_client,
            slack_bot_client=slack_bot_client,
            message=QUESTION_LENA_BOOKS,
            channel=channel,
            tag_bot=True,
        )
        assert message is not None, f"{test_name}: Bot should respond in {channel_name}"
        blocks = message["blocks"]
        assert (
            blocks is not None and len(blocks) > 0
        ), f"{test_name}: Response should have blocks in {channel_name}"
        assert_button_presence(
            blocks, "followup-button", expect_button, test_name, channel_name
        )


@pytest.mark.parametrize(
    "test_name, channel_1_config, channel_2_config, expected_text_channel_1, expected_text_channel_2, message_text",
    [
        (
            "enabled_in_both",
            {
                "respond_to_bots": True,
                "answer_filters": ["questionmark_prefilter"],
                "respond_tag_only": False,
            },
            {
                "respond_to_bots": True,
                "answer_filters": ["questionmark_prefilter"],
                "respond_tag_only": False,
            },
            None,
            None,
            QUESTION_LENA_BOOKS_NO_MARK,
        ),
        (
            "enabled_in_channel_1_only",
            {
                "respond_to_bots": True,
                "answer_filters": ["questionmark_prefilter"],
                "respond_tag_only": False,
            },
            {"respond_to_bots": True, "respond_tag_only": False},
            None,
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
            QUESTION_LENA_BOOKS_NO_MARK,
        ),
        (
            "disabled_in_both",
            {"respond_to_bots": True, "respond_tag_only": False},
            {"respond_to_bots": True, "respond_tag_only": False},
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
            QUESTION_LENA_BOOKS_NO_MARK,
        ),
        (
            "enabled_in_both_with_question",
            {
                "respond_to_bots": True,
                "answer_filters": ["questionmark_prefilter"],
                "respond_tag_only": False,
            },
            {
                "respond_to_bots": True,
                "answer_filters": ["questionmark_prefilter"],
                "respond_tag_only": False,
            },
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
            QUESTION_LENA_BOOKS,
        ),
    ],
)
def test_respond_to_questions(
    slack_test_context: SlackTestContext,
    test_name: str,
    channel_1_config: dict[str, Any],
    channel_2_config: dict[str, Any],
    expected_text_channel_1: list[str] | None,
    expected_text_channel_2: list[str] | None,
    message_text: str,
):
    """Verify the 'respond to questions' filter (question mark prefilter) in channels."""
    logger.info(f"Running test: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]
    test_channel_1 = slack_test_context.test_channel_1
    test_channel_2 = slack_test_context.test_channel_2

    # Update channel 1 config
    logger.info(f"test_channel_1 : {test_channel_1}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        channel_name=test_channel_1["name"],
        updated_config_data=channel_1_config,
    )
    # Update default config (applies to channel 2)
    logger.info(f"Channel 2 config: {channel_2_config}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        updated_config_data=channel_2_config,
    )

    for channel, expected_text, channel_name in [
        (test_channel_1, expected_text_channel_1, "test_channel_1"),
        (test_channel_2, expected_text_channel_2, "test_channel_2"),
    ]:
        message = send_channel_msg_with_optional_timeout(
            slack_bot_client=slack_bot_client,
            slack_user_client=slack_user_client,
            message_text=message_text,
            channel=channel,
            expected_text=expected_text,
        )
        if expected_text is None:
            assert (
                message is None
            ), f"{test_name}: Bot should not respond in {channel_name}"
            continue
        assert message is not None, f"{test_name}: Bot should respond in {channel_name}"
        blocks = message["blocks"]
        assert (
            blocks is not None and len(blocks) > 0
        ), f"{test_name}: Response should have blocks in {channel_name}"
        assert any(
            text in blocks[0]["text"]["text"] for text in expected_text
        ), f"{test_name}: Response should contain one of '{expected_text}'"


@pytest.mark.parametrize(
    "test_name, channel_1_config, channel_2_config, expected_text_channel_1, expected_text_channel_2",
    [
        (
            "enabled_in_both",
            "std_ans_category",
            "std_ans_category",
            STD_ANSWER_SUPPORT_EMAIL,
            STD_ANSWER_SUPPORT_EMAIL,
        ),
        (
            "enabled_in_channel_1_only",
            "std_ans_category",
            {"respond_to_bots": True},
            STD_ANSWER_SUPPORT_EMAIL,
            None,
        ),
        (
            "disabled_in_both",
            {"respond_to_bots": True},
            {"respond_to_bots": True},
            None,
            None,
        ),
    ],
)
def test_standard_answer(
    slack_test_context: SlackTestContext,
    test_name: str,
    channel_1_config: dict[str, Any] | str,
    channel_2_config: dict[str, Any] | str,
    expected_text_channel_1: str | None,
    expected_text_channel_2: str | None,
):
    """Verify the standard answer category functionality in channels."""
    logger.info(f"Running test: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]
    test_channel_1 = slack_test_context.test_channel_1
    test_channel_2 = slack_test_context.test_channel_2

    # Update channel 1 config
    logger.info(f"test_channel_1 : {test_channel_1}")
    if channel_1_config == "std_ans_category":
        categories = slack_test_context.std_ans_category
        cat_id = categories["id"]
        channel_1_config = {
            "respond_to_bots": True,
            "standard_answer_categories": [cat_id],
        }

    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        channel_name=test_channel_1["name"],
        updated_config_data=channel_1_config,
    )
    # Update default config (applies to channel 2)
    logger.info(f"Channel 2 config: {channel_2_config}")
    if channel_2_config == "std_ans_category":
        categories = slack_test_context.std_ans_category
        cat_id = categories["id"]
        channel_2_config = {
            "respond_to_bots": True,
            "standard_answer_categories": [cat_id],
        }
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        updated_config_data=channel_2_config,
    )
    for channel, expected_text, channel_name in [
        (test_channel_1, expected_text_channel_1, "test_channel_1"),
        (test_channel_2, expected_text_channel_2, "test_channel_2"),
    ]:
        message = send_channel_msg_with_optional_timeout(
            slack_bot_client=slack_bot_client,
            slack_user_client=slack_user_client,
            message_text=QUESTION_NEED_SUPPORT,
            channel=channel,
            expected_text=expected_text,
            tag_bot=True,
        )
        assert message is not None, f"{test_name}: Bot should respond in {channel_name}"
        blocks = message["blocks"]
        if expected_text is None:
            assert (
                STD_ANSWER_SUPPORT_EMAIL not in blocks[0]["text"]["text"]
            ), f"{test_name}: Response should NOT contain the standard answer in {channel_name}"
        else:
            assert (
                expected_text in blocks[0]["text"]["text"]
            ), f"{test_name}: Response should contain '{expected_text}'"


@pytest.mark.parametrize(
    "test_name, channel_1_config, channel_2_config, expected_text_channel_1, expected_text_channel_2",
    [
        (
            "disabled_in_both_respond_to_bots",
            {"respond_to_bots": False},
            {"respond_to_bots": False},
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
        (
            "respond_to_bots_enabled_respond_to_questions_enabled",
            {"respond_to_bots": False, "answer_filters": ["questionmark_prefilter"]},
            {"respond_to_bots": False, "answer_filters": ["questionmark_prefilter"]},
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
        (
            "config_disabled",
            {"disabled": True},
            {"disabled": True},
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
    ],
)
def test_tag_with_restriction(
    slack_test_context: SlackTestContext,
    test_name: str,
    channel_1_config: dict[str, Any],
    channel_2_config: dict[str, Any],
    expected_text_channel_1: list[str],
    expected_text_channel_2: list[str],
):
    """Verify that the bot responds when tagged, even if 'Respond to Bots' is disabled,
    'Respond to Questions' is enabled, or the overall channel configuration is disabled.
    """
    logger.info(f"Running test: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]
    test_channel_1 = slack_test_context.test_channel_1
    test_channel_2 = slack_test_context.test_channel_2

    # Update channel 1 config
    logger.info(f"test_channel_1 : {test_channel_1}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        channel_name=test_channel_1["name"],
        updated_config_data=channel_1_config,
    )
    # Update default config (applies to channel 2)
    logger.info(f"Channel 2 config: {channel_2_config}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        updated_config_data=channel_2_config,
    )

    for channel, expected_text, channel_name in [
        (test_channel_1, expected_text_channel_1, "test_channel_1"),
        (test_channel_2, expected_text_channel_2, "test_channel_2"),
    ]:
        message = send_and_receive_channel_message(
            slack_user_client=slack_user_client,
            slack_bot_client=slack_bot_client,
            message=QUESTION_LENA_BOOKS_NO_MARK,
            channel=channel,
            tag_bot=True,
        )
        assert message is not None, f"{test_name}: Bot should respond in {channel_name}"
        blocks = message["blocks"]
        assert (
            blocks is not None and len(blocks) > 0
        ), f"{test_name}: Response should have blocks in {channel_name}"
        assert any(
            text in blocks[0]["text"]["text"] for text in expected_text
        ), f"{test_name}: Response should contain one of '{expected_text}'"


@pytest.mark.xfail(
    reason="Skipping the test on failure, as we are currently receiving a response regardless of whether a citation is present."
)
@pytest.mark.parametrize(
    "test_name, channel_1_config, channel_2_config, expected_text_channel_1, expected_text_channel_2, message_text",
    [
        (
            "enabled_in_both",
            {"respond_to_bots": True, "answer_filters": ["well_answered_postfilter"]},
            {"respond_to_bots": True, "answer_filters": ["well_answered_postfilter"]},
            None,
            None,
            QUESTION_CAPITAL_FRANCE,
        ),
        (
            "enabled_in_channel_1_only",
            {"respond_to_bots": True, "answer_filters": ["well_answered_postfilter"]},
            {"respond_to_bots": True},
            None,
            "",
            QUESTION_CAPITAL_FRANCE,
        ),
        (
            "disabled_in_both",
            {"respond_to_bots": True},
            {"respond_to_bots": True},
            "",
            "",
            QUESTION_CAPITAL_FRANCE,
        ),
    ],
)
def test_citation(
    slack_test_context: SlackTestContext,
    test_name: str,
    channel_1_config: dict[str, Any],
    channel_2_config: dict[str, Any],
    expected_text_channel_1: str | None,
    expected_text_channel_2: str | None,
    message_text: str,
):
    """Verify the citation filter ('well_answered_postfilter') functionality in channels."""
    logger.info(f"Running test: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]
    test_channel_1 = slack_test_context.test_channel_1
    test_channel_2 = slack_test_context.test_channel_2

    # Update channel 1 config
    logger.info(f"test_channel_1 : {test_channel_1}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        channel_name=test_channel_1["name"],
        updated_config_data=channel_1_config,
    )
    # Update default config (applies to channel 2)
    logger.info(f"Channel 2 config: {channel_2_config}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        updated_config_data=channel_2_config,
    )

    for channel, expected_text, channel_name in [
        (test_channel_1, expected_text_channel_1, "test_channel_1"),
        (test_channel_2, expected_text_channel_2, "test_channel_2"),
    ]:
        message = send_and_receive_channel_message(
            slack_user_client=slack_user_client,
            slack_bot_client=slack_bot_client,
            message=message_text,
            channel=channel,
            tag_bot=True,
        )
        if expected_text is None:
            assert (
                message is None
            ), f"{test_name}: Bot should not respond in {channel_name}"
            continue
        assert message is not None, f"{test_name}: Bot should respond in {channel_name}"


@pytest.mark.xfail(
    reason="Skipping the test on failure, sometimes we are getting correct response and sometimes not."
)
def test_llm_auto_filter(slack_test_context: SlackTestContext):
    """Verify the LLM auto-filter functionality in channels."""
    logger.info("Running test: llm_auto_filter")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]
    test_channel_1 = slack_test_context.test_channel_1
    test_channel_2 = slack_test_context.test_channel_2

    # Update channel 1 config
    logger.info(f"test_channel_1 : {test_channel_1}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        channel_name=test_channel_1["name"],
        updated_config_data={"enable_auto_filters": True},
    )
    # Update default config (applies to channel 2)
    logger.info(f"Channel 2 config: {test_channel_2}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        updated_config_data={"enable_auto_filters": True},
    )

    for channel in [test_channel_1, test_channel_2]:
        message = send_and_receive_channel_message(
            slack_user_client=slack_user_client,
            slack_bot_client=slack_bot_client,
            message=QUESTION_LENA_BOOKS_WEB_SOURCE,
            channel=channel,
            tag_bot=True,
        )
        assert message is not None, "Bot should respond"
        blocks = message["blocks"]
        assert blocks is not None and len(blocks) > 0, "Response should have blocks"
        assert (
            ANSWER_LENA_BOOKS_WEB in blocks[0]["text"]["text"]
        ), "Response should contain '40'"


@pytest.mark.parametrize(
    "test_name, channel_1_config, channel_2_config, expected_text_primary_user, expected_text_secondary_user",
    [
        (
            "enabled_in_both",
            {
                "respond_to_bots": True,
                "respond_member_group_list": ["subashmohan75@gmail.com"],
                "respond_tag_only": False,
            },
            {
                "respond_to_bots": True,
                "respond_member_group_list": ["support"],
                "respond_tag_only": False,
            },
            None,
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
        (
            "disabled_in_both",
            {"respond_to_bots": True},
            {"respond_to_bots": True},
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
            [ANSWER_LENA_BOOKS_STORY, ANSWER_LENA_BOOKS_WEB],
        ),
    ],
)
def test_respond_to_certain_users_or_groups(
    slack_test_context: SlackTestContext,
    test_name: str,
    channel_1_config: dict[str, Any],
    channel_2_config: dict[str, Any],
    expected_text_primary_user: list[str] | None,
    expected_text_secondary_user: list[str],
):
    """Verify the functionality to restrict bot responses to specific users or groups in channels."""
    logger.info(f"Running test: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]
    test_channel_1 = slack_test_context.test_channel_1
    test_channel_2 = slack_test_context.test_channel_2
    # Update channel 1 config
    logger.info(f"test_channel_1 : {test_channel_1}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        channel_name=test_channel_1["name"],
        updated_config_data=channel_1_config,
    )
    # Update default config (applies to channel 2)
    logger.info(f"Channel 2 config: {channel_2_config}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        updated_config_data=channel_2_config,
    )

    for channel in [test_channel_1, test_channel_2]:
        ts = send_message_to_channel(
            slack_user_client=slack_user_client,
            slack_bot_client=slack_bot_client,
            message=QUESTION_LENA_BOOKS,
            channel=channel,
            tag_bot=True,
        )
        assert ts is not None, "Bot should respond"
        reply = SlackManager.poll_for_reply(
            slack_user_client,
            channel=channel,
            original_message_ts=ts,
            timeout_seconds=DEFAULT_REPLY_TIMEOUT,
        )
        logger.info(f"Received message as primary user: {reply}")
        assert reply is not None, "Bot should respond"
        if expected_text_primary_user is None:
            assert (
                ANSWER_LENA_BOOKS_STORY not in reply["text"]
                and ANSWER_LENA_BOOKS_WEB not in reply["text"]
            ), "Response should NOT contain '42' or '40'"
        else:
            blocks = reply["blocks"]
            assert blocks is not None and len(blocks) > 0, "Response should have blocks"
            assert any(
                text in blocks[0]["text"]["text"] for text in expected_text_primary_user
            ), f"Response should contain one of '{expected_text_primary_user}'"

        with get_session_context_manager() as session:
            user = get_primary_user_record(session)
            user_id = user.id
            logger.info(f"Slack user ID: {user_id}")
            _, messages = get_last_chat_session_and_messages(
                user_id=user_id, db_session=session
            )
            assert (
                messages is not None and len(messages) > 0
            ), "Response should have messages"
            for message in messages:
                if message.message_type == "ASSISTANT":
                    assert message.message is not None, "Response should have messages"
                    assert any(
                        text in message.message for text in expected_text_secondary_user
                    ), f"Response should contain one of '{expected_text_secondary_user}'"


@pytest.mark.parametrize(
    "test_name, channel_1_config, channel_2_config, expected_text_primary_user",
    [
        (
            "enabled_in_both",
            {"respond_to_bots": True, "is_ephemeral": True},
            {"respond_to_bots": True, "is_ephemeral": True},
            EPHEMERAL_MESSAGE_ANSWER,
        ),
        (
            "disabled_in_both",
            {"respond_to_bots": True},
            {"respond_to_bots": True},
            None,
        ),
    ],
)
def test_ephemeral_message(
    slack_test_context: SlackTestContext,
    test_name: str,
    channel_1_config: dict[str, Any],
    channel_2_config: dict[str, Any],
    expected_text_primary_user: str | None,
):
    """Verify the ephemeral message functionality in channels."""
    logger.info(f"Running test: {test_name}")
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    slack_secondary_user_client = slack_test_context.slack_secondary_user_client
    admin_user = slack_test_context.admin_user
    bot_id = slack_test_context.slack_bot["id"]
    test_channel_1 = slack_test_context.test_channel_1
    test_channel_2 = slack_test_context.test_channel_2
    # Update channel 1 config
    logger.info(f"test_channel_1 : {test_channel_1}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        channel_name=test_channel_1["name"],
        updated_config_data=channel_1_config,
    )
    # Update default config (applies to channel 2)
    logger.info(f"Channel 2 config: {channel_2_config}")
    update_channel_config(
        bot_id=bot_id,
        user_performing_action=admin_user,
        updated_config_data=channel_2_config,
    )
    for channel in [test_channel_1, test_channel_2]:
        ts = send_message_to_channel(
            slack_user_client=slack_user_client,
            slack_bot_client=slack_bot_client,
            message=EPHEMERAL_MESSAGE_QUESTION,
            channel=channel,
            tag_bot=True,
        )
        assert ts is not None, "Bot should respond"
        if expected_text_primary_user is not None:
            time.sleep(SLEEP_BEFORE_EPHEMERAL_CHECK)
            with get_session_context_manager() as session:
                user = get_primary_user_record(session)
                user_id = user.id
                logger.info(f"Slack user ID: {user_id}")
                _, messages = get_last_chat_session_and_messages(
                    user_id=user_id, db_session=session
                )
                assert (
                    messages is not None and len(messages) > 0
                ), "Response should have messages"
                for message in messages:
                    if message.message_type == "ASSISTANT":
                        assert (
                            message.message is not None
                        ), "Response should have messages"
                        assert (
                            expected_text_primary_user in message.message
                        ), f"Response should contain '{expected_text_primary_user}'"
            reply = SlackManager.poll_for_reply(
                slack_secondary_user_client,
                channel=channel,
                original_message_ts=ts,
                timeout_seconds=SHORT_REPLY_TIMEOUT,
            )
            assert reply is None, "Bot should not respond"
        else:
            reply = SlackManager.poll_for_reply(
                slack_user_client,
                channel=channel,
                original_message_ts=ts,
                timeout_seconds=DEFAULT_REPLY_TIMEOUT,
            )
            assert reply is not None, "Bot should respond"
            blocks = reply["blocks"]
            assert blocks is not None and len(blocks) > 0, "Response should have blocks"
            assert (
                EPHEMERAL_MESSAGE_ANSWER not in blocks[0]["text"]["text"]
            ), f"Response should not contain '{EPHEMERAL_MESSAGE_ANSWER}'"

            reply = SlackManager.poll_for_reply(
                slack_secondary_user_client,
                channel=channel,
                original_message_ts=ts,
                timeout_seconds=DEFAULT_REPLY_TIMEOUT,
            )
            assert reply is not None, "Bot should respond"
            blocks = reply["blocks"]
            assert blocks is not None and len(blocks) > 0, "Response should have blocks"
            assert (
                EPHEMERAL_MESSAGE_ANSWER not in blocks[0]["text"]["text"]
            ), f"Response should not contain '{EPHEMERAL_MESSAGE_ANSWER}'"
