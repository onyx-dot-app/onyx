from slack_sdk import WebClient
from sqlalchemy.orm import Session

from danswer.configs.constants import MessageType
from danswer.configs.danswerbot_configs import DANSWER_REACT_EMOJI
from danswer.danswerbot.slack.blocks import build_standard_answer_blocks
from danswer.danswerbot.slack.blocks import get_restate_blocks
from danswer.danswerbot.slack.handlers.utils import send_team_member_message
from danswer.danswerbot.slack.models import SlackMessageInfo
from danswer.danswerbot.slack.utils import respond_in_thread
from danswer.danswerbot.slack.utils import update_emote_react
from danswer.db.chat import create_chat_session
from danswer.db.chat import create_new_chat_message
from danswer.db.chat import get_chat_messages_by_sessions
from danswer.db.chat import get_chat_sessions_by_slack_thread_id
from danswer.db.chat import get_or_create_root_message
from danswer.db.models import Prompt
from danswer.db.models import SlackBotConfig
from danswer.db.standard_answer import fetch_standard_answer_categories_by_names
from danswer.db.standard_answer import find_matching_standard_answers
from danswer.server.manage.models import StandardAnswer
from danswer.utils.logger import DanswerLoggingAdapter
from danswer.utils.logger import setup_logger

logger = setup_logger()


def oneoff_standard_answers(
    message: str,
    slack_bot_categories: list[str],
    db_session: Session,
) -> list[StandardAnswer]:
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
        StandardAnswer.from_model(db_answer) for db_answer in matching_standard_answers
    ]
    return server_standard_answers


def handle_standard_answers(
    message_info: SlackMessageInfo,
    receiver_ids: list[str] | None,
    slack_bot_config: SlackBotConfig | None,
    prompt: Prompt | None,
    logger: DanswerLoggingAdapter,
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
    # if no channel config, then no standard answers are configured
    if not slack_bot_config:
        return False

    slack_thread_id = message_info.thread_to_respond
    configured_standard_answer_categories = (
        slack_bot_config.standard_answer_categories if slack_bot_config else []
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
    if usable_standard_answers:
        matching_standard_answers = find_matching_standard_answers(
            query=query_msg.message,
            id_in=[standard_answer.id for standard_answer in usable_standard_answers],
            db_session=db_session,
        )
    else:
        matching_standard_answers = []
    if matching_standard_answers:
        chat_session = create_chat_session(
            db_session=db_session,
            description="",
            user_id=None,
            persona_id=slack_bot_config.persona.id if slack_bot_config.persona else 0,
            danswerbot_flow=True,
            slack_thread_id=slack_thread_id,
            one_shot=True,
        )

        root_message = get_or_create_root_message(
            chat_session_id=chat_session.id, db_session=db_session
        )

        new_user_message = create_new_chat_message(
            chat_session_id=chat_session.id,
            parent_message=root_message,
            prompt_id=prompt.id if prompt else None,
            message=query_msg.message,
            token_count=0,
            message_type=MessageType.USER,
            db_session=db_session,
            commit=True,
        )

        formatted_answers = []
        for standard_answer in matching_standard_answers:
            block_quotified_answer = ">" + standard_answer.answer.replace("\n", "\n> ")
            formatted_answer = (
                f'Since you mentioned _"{standard_answer.keyword}"_, '
                f"I thought this might be useful: \n\n{block_quotified_answer}"
            )
            formatted_answers.append(formatted_answer)
        answer_message = "\n\n".join(formatted_answers)

        _ = create_new_chat_message(
            chat_session_id=chat_session.id,
            parent_message=new_user_message,
            prompt_id=prompt.id if prompt else None,
            message=answer_message,
            token_count=0,
            message_type=MessageType.ASSISTANT,
            error=None,
            db_session=db_session,
            commit=True,
        )

        update_emote_react(
            emoji=DANSWER_REACT_EMOJI,
            channel=message_info.channel_to_respond,
            message_ts=message_info.msg_to_respond,
            remove=True,
            client=client,
        )

        restate_question_blocks = get_restate_blocks(
            msg=query_msg.message,
            is_bot_msg=message_info.is_bot_msg,
        )

        answer_blocks = build_standard_answer_blocks(
            answer_message=answer_message,
        )

        all_blocks = restate_question_blocks + answer_blocks

        try:
            respond_in_thread(
                client=client,
                channel=message_info.channel_to_respond,
                receiver_ids=receiver_ids,
                text="Hello! Danswer has some results for you!",
                blocks=all_blocks,
                thread_ts=message_info.msg_to_respond,
                unfurl=False,
            )

            if receiver_ids and slack_thread_id:
                send_team_member_message(
                    client=client,
                    channel=message_info.channel_to_respond,
                    thread_ts=slack_thread_id,
                )

            return True
        except Exception as e:
            logger.exception(f"Unable to send standard answer message: {e}")
            return False
    else:
        return False
