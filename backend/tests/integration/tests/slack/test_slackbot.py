import pytest

from onyx.db.engine import get_session_context_manager
from onyx.db.slack_bot import fetch_slack_bot
from onyx.utils.logger import setup_logger
from tests.integration.common_utils.test_models import SlackTestContext
from tests.integration.tests.slack.constants import QUESTION_LENA_BOOKS
from tests.integration.tests.slack.constants import SHORT_REPLY_TIMEOUT
from tests.integration.tests.slack.slack_test_helpers import (
    send_and_receive_channel_message,
)
from tests.integration.tests.slack.slack_test_helpers import send_and_receive_dm
from tests.integration.tests.slack.utils import delete_slack_bot
from tests.integration.tests.slack.utils import get_slack_bot
from tests.integration.tests.slack.utils import update_slack_bot

logger = setup_logger()


def test_disable_slack_bot(slack_test_context: SlackTestContext):
    """Test the disabling of a Slack bot."""
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    test_channel_1 = slack_test_context.test_channel_1
    test_channel_2 = slack_test_context.test_channel_2
    bot_id = slack_test_context.slack_bot["id"]
    user_performing_action = slack_test_context.admin_user

    # Disable the bot
    bot_data = get_slack_bot(
        bot_id=bot_id,
        user_performing_action=user_performing_action,
    )
    update_body = {
        "name": bot_data.get("name"),
        "enabled": False,
        "bot_token": bot_data.get("bot_token"),
        "app_token": bot_data.get("app_token"),
    }
    update_slack_bot(
        bot_id=bot_id,
        user_performing_action=user_performing_action,
        update_body=update_body,
    )

    # send a message to the bot in dm and check for a response
    message = send_and_receive_dm(
        slack_bot_client,
        slack_user_client,
        QUESTION_LENA_BOOKS,
        timeout_secs=SHORT_REPLY_TIMEOUT,
    )

    assert message is None, "Expected no response from the disabled bot"

    # send a message to the bot in channel 1 and check for a response
    message = send_and_receive_channel_message(
        slack_user_client=slack_user_client,
        slack_bot_client=slack_bot_client,
        message=QUESTION_LENA_BOOKS,
        channel=test_channel_1,
        timeout_secs=SHORT_REPLY_TIMEOUT,
    )

    assert message is None, "Expected no response from the disabled bot"

    # send a message to the bot in channel 2 and check for a response
    message = send_and_receive_channel_message(
        slack_user_client=slack_user_client,
        slack_bot_client=slack_bot_client,
        message=QUESTION_LENA_BOOKS,
        channel=test_channel_2,
        timeout_secs=SHORT_REPLY_TIMEOUT,
    )

    assert message is None, "Expected no response from the disabled bot"

    # Enable the bot
    update_body["enabled"] = True
    update_slack_bot(
        bot_id=bot_id,
        user_performing_action=user_performing_action,
        update_body=update_body,
    )


@pytest.mark.order(-1)
def test_delete_slack_bot(slack_test_context: SlackTestContext):
    """Test the deletion of a Slack bot."""
    slack_bot_client = slack_test_context.slack_bot_client
    slack_user_client = slack_test_context.slack_user_client
    test_channel_1 = slack_test_context.test_channel_1
    test_channel_2 = slack_test_context.test_channel_2
    bot_id = slack_test_context.slack_bot["id"]
    user_performing_action = slack_test_context.admin_user

    delete_slack_bot(
        bot_id=bot_id,
        user_performing_action=user_performing_action,
    )

    # Verify that the bot is deleted
    with get_session_context_manager() as session:
        with pytest.raises(ValueError):
            fetch_slack_bot(db_session=session, slack_bot_id=bot_id)

    message = send_and_receive_dm(
        slack_bot_client,
        slack_user_client,
        QUESTION_LENA_BOOKS,
        timeout_secs=SHORT_REPLY_TIMEOUT,
    )

    assert message is None, "Expected no response from the deleted bot"

    message = send_and_receive_channel_message(
        slack_user_client=slack_user_client,
        slack_bot_client=slack_bot_client,
        message=QUESTION_LENA_BOOKS,
        channel=test_channel_1,
        timeout_secs=SHORT_REPLY_TIMEOUT,
    )

    assert message is None, "Expected no response from the deleted bot"

    message = send_and_receive_channel_message(
        slack_user_client=slack_user_client,
        slack_bot_client=slack_bot_client,
        message=QUESTION_LENA_BOOKS,
        channel=test_channel_2,
        timeout_secs=SHORT_REPLY_TIMEOUT,
    )
    assert message is None, "Expected no response from the deleted bot"
