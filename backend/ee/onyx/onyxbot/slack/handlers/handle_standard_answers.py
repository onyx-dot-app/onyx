from slack_sdk import WebClient
from slack_sdk.models.blocks import ActionsBlock
from slack_sdk.models.blocks import Block
from slack_sdk.models.blocks import ButtonElement
from slack_sdk.models.blocks import SectionBlock
from sqlalchemy.orm import Session

from ee.onyx.db.standard_answer import fetch_standard_answer_categories_by_names
from ee.onyx.db.standard_answer import find_matching_standard_answers
from onyx.configs.constants import MessageType
from onyx.configs.onyxbot_configs import ONYX_BOT_REACT_EMOJI
from onyx.db.chat import create_chat_session
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_chat_messages_by_sessions
from onyx.db.chat import get_chat_sessions_by_slack_thread_id
from onyx.db.chat import get_or_create_root_message
from onyx.db.models import SlackChannelConfig
from onyx.db.models import StandardAnswer as StandardAnswerModel
from onyx.onyxbot.slack.blocks import get_restate_blocks
from onyx.onyxbot.slack.constants import GENERATE_ANSWER_BUTTON_ACTION_ID
from onyx.onyxbot.slack.handlers.utils import send_team_member_message
from onyx.onyxbot.slack.models import SlackMessageInfo
from onyx.onyxbot.slack.utils import respond_in_thread_or_channel
from onyx.onyxbot.slack.utils import update_emote_react
from onyx.server.manage.models import StandardAnswer as PydanticStandardAnswer
from onyx.utils.logger import OnyxLoggingAdapter
from onyx.utils.logger import setup_logger

logger = setup_logger()


def build_standard_answer_blocks(
    answer_message: str,
) -> list[Block]:
    generate_button_block = ButtonElement(
        action_id=GENERATE_ANSWER_BUTTON_ACTION_ID,
        text="Generate Full Answer",
    )
    answer_block = SectionBlock(text=answer_message)
    return [
        answer_block,
        ActionsBlock(
            elements=[generate_button_block],
        ),
    ]


def oneoff_standard_answers(
    message: str,
    slack_bot_categories: list[str],
    db_session: Session,
) -> list[PydanticStandardAnswer]:
    """
    Respond to the user message if it matches any configured standard answers.

    Returns a list of matching StandardAnswers if found, otherwise None.
    """
    configured_standard_answers = {
        standard_answer
        for category in fetch_standard_answer_categories_by_names(
            slack_bot_categories, db_session=db_session
        )
        for standard_answer in category.standard_answers
    }

    matching_standard_answers = find_matching_standard_answers(
        query=message,
        id_in=[answer.id for answer in configured_standard_answers],
        db_session=db_session,
    )

    server_standard_answers = [
        PydanticStandardAnswer.from_model(standard_answer_model)
        for (standard_answer_model, _) in matching_standard_answers
    ]
    return server_standard_answers


def _handle_standard_answers(
    message_info: SlackMessageInfo,
    receiver_ids: list[str] | None,
    slack_channel_config: SlackChannelConfig,
    logger: OnyxLoggingAdapter,
    client: WebClient,
    db_session: Session,
) -> bool:
    """
    Potentially respond to the user message depending on whether the user's message matches
    any of the configured standard answers and also whether those answers have already been
    provided in the current thread.

    Returns True if standard answers are found to match the user's message and therefore,
    we still need to respond to the users.
    """

    slack_thread_id = message_info.thread_to_respond
    configured_standard_answer_categories = (
        slack_channel_config.standard_answer_categories
    )
    configured_standard_answers = set(
        [
            standard_answer
            for standard_answer_category in configured_standard_answer_categories
            for standard_answer in standard_answer_category.standard_answers
        ]
    )
    query_msg = message_info.thread_messages[-1]

    if slack_thread_id is None:
        used_standard_answer_ids = set([])
    else:
        chat_sessions = get_chat_sessions_by_slack_thread_id(
            slack_thread_id=slack_thread_id,
            user_id=None,
            db_session=db_session,
        )
        chat_messages = get_chat_messages_by_sessions(
            chat_session_ids=[chat_session.id for chat_session in chat_sessions],
            user_id=None,
            db_session=db_session,
            skip_permission_check=True,
        )
        used_standard_answer_ids = set(
            [
                standard_answer.id
                for chat_message in chat_messages
                for standard_answer in chat_message.standard_answers
            ]
        )

    usable_standard_answers = configured_standard_answers.difference(
        used_standard_answer_ids
    )

    matching_standard_answers: list[tuple[StandardAnswerModel, str]] = []
    if usable_standard_answers:
        matching_standard_answers = find_matching_standard_answers(
            query=query_msg.message,
            id_in=[standard_answer.id for standard_answer in usable_standard_answers],
            db_session=db_session,
        )

    if matching_standard_answers:
        chat_session = create_chat_session(
            db_session=db_session,
            description="",
            user_id=None,
            persona_id=(
                slack_channel_config.persona.id if slack_channel_config.persona else 0
            ),
            onyxbot_flow=True,
            slack_thread_id=slack_thread_id,
        )

        root_message = get_or_create_root_message(
            chat_session_id=chat_session.id, db_session=db_session
        )

        new_user_message = create_new_chat_message(
            chat_session_id=chat_session.id,
            parent_message=root_message,
            message=query_msg.message,
            token_count=0,
            message_type=MessageType.USER,
            db_session=db_session,
            commit=True,
        )

        formatted_answers = []
        for standard_answer, match_str in matching_standard_answers:
            since_you_mentioned_pretext = (
                f'Since your question contains "_{match_str}_"'
            )
            block_quotified_answer = ">" + standard_answer.answer.replace("\n", "\n> ")
            formatted_answer = f"{since_you_mentioned_pretext}, I thought this might be useful: \n\n{block_quotified_answer}"
            formatted_answers.append(formatted_answer)
        answer_message = "\n\n".join(formatted_answers)

        chat_message = create_new_chat_message(
            chat_session_id=chat_session.id,
            parent_message=new_user_message,
            message=answer_message,
            token_count=0,
            message_type=MessageType.ASSISTANT,
            error=None,
            db_session=db_session,
            commit=False,
        )
        # attach the standard answers to the chat message
        chat_message.standard_answers = [
            standard_answer for standard_answer, _ in matching_standard_answers
        ]
        db_session.commit()

        update_emote_react(
            emoji=ONYX_BOT_REACT_EMOJI,
            channel=message_info.channel_to_respond,
            message_ts=message_info.msg_to_respond,
            remove=True,
            client=client,
        )

        restate_question_blocks = get_restate_blocks(
            msg=query_msg.message,
            is_slash_command=message_info.is_slash_command,
        )

        answer_blocks = build_standard_answer_blocks(
            answer_message=answer_message,
        )

        all_blocks = restate_question_blocks + answer_blocks

        try:
            respond_in_thread_or_channel(
                client=client,
                channel=message_info.channel_to_respond,
                receiver_ids=receiver_ids,
                text="Hello! Onyx has some results for you!",
                blocks=all_blocks,
                thread_ts=message_info.msg_to_respond,
                unfurl=False,
            )

            if receiver_ids and slack_thread_id:
                send_team_member_message(
                    client=client,
                    channel=message_info.channel_to_respond,
                    thread_ts=slack_thread_id,
                    receiver_ids=receiver_ids,
                )

            return True
        except Exception as e:
            logger.exception(f"Unable to send standard answer message: {e}")
            return False
    else:
        return False
