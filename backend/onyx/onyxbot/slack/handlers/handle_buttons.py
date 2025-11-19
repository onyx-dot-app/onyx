import json
from typing import Any
from typing import cast

from slack_sdk import WebClient
from slack_sdk.models.blocks import SectionBlock
from slack_sdk.models.views import View
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.webhook import WebhookClient

from onyx.chat.models import ChatBasicResponse
from onyx.chat.process_message import remove_answer_citations
from onyx.configs.constants import MessageType
from onyx.configs.constants import SearchFeedbackType
from onyx.configs.onyxbot_configs import ONYX_BOT_FOLLOWUP_EMOJI
from onyx.connectors.slack.utils import expert_info_from_slack_id
from onyx.context.search.models import SavedSearchDoc
from onyx.db.chat import get_chat_message
from onyx.db.chat import translate_db_message_to_chat_message_detail
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.feedback import create_chat_message_feedback
from onyx.db.feedback import create_doc_retrieval_feedback
from onyx.db.users import get_user_by_email
from onyx.onyxbot.slack.blocks import build_follow_up_resolved_blocks
from onyx.onyxbot.slack.blocks import build_slack_response_blocks
from onyx.onyxbot.slack.blocks import get_document_feedback_blocks
from onyx.onyxbot.slack.config import get_slack_channel_config_for_bot_and_channel
from onyx.onyxbot.slack.constants import DISLIKE_BLOCK_ACTION_ID
from onyx.onyxbot.slack.constants import FeedbackVisibility
from onyx.onyxbot.slack.constants import KEEP_TO_YOURSELF_ACTION_ID
from onyx.onyxbot.slack.constants import LIKE_BLOCK_ACTION_ID
from onyx.onyxbot.slack.constants import SHOW_EVERYONE_ACTION_ID
from onyx.onyxbot.slack.constants import VIEW_DOC_FEEDBACK_ID
from onyx.onyxbot.slack.handlers.handle_message import (
    remove_scheduled_feedback_reminder,
)
from onyx.onyxbot.slack.handlers.handle_regular_answer import (
    handle_regular_answer,
)
from onyx.onyxbot.slack.models import SlackMessageInfo
from onyx.onyxbot.slack.utils import build_feedback_id
from onyx.onyxbot.slack.utils import decompose_action_id
from onyx.onyxbot.slack.utils import fetch_group_ids_from_names
from onyx.onyxbot.slack.utils import fetch_slack_user_ids_from_emails
from onyx.onyxbot.slack.utils import get_channel_name_from_id
from onyx.onyxbot.slack.utils import get_feedback_visibility
from onyx.onyxbot.slack.utils import read_slack_thread
from onyx.onyxbot.slack.utils import respond_in_thread_or_channel
from onyx.onyxbot.slack.utils import TenantSocketModeClient
from onyx.onyxbot.slack.utils import update_emote_react
from onyx.server.query_and_chat.models import ChatMessageDetail
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.utils.logger import setup_logger


logger = setup_logger()


def _convert_db_doc_id_to_document_ids(
    citation_dict: dict[int, int], top_documents: list[SavedSearchDoc]
) -> list[CitationInfo]:
    citation_list_with_document_id = []
    for citation_num, db_doc_id in citation_dict.items():
        if db_doc_id is not None:
            matching_doc = next(
                (d for d in top_documents if d.db_doc_id == db_doc_id), None
            )
            if matching_doc:
                citation_list_with_document_id.append(
                    CitationInfo(
                        citation_num=citation_num, document_id=matching_doc.document_id
                    )
                )
    return citation_list_with_document_id


def _build_citation_list(chat_message_detail: ChatMessageDetail) -> list[CitationInfo]:
    citation_dict = chat_message_detail.citations
    if citation_dict is None:
        return []
    else:
        top_documents = (
            chat_message_detail.context_docs.top_documents
            if chat_message_detail.context_docs
            else []
        )
        citation_list = _convert_db_doc_id_to_document_ids(citation_dict, top_documents)
        return citation_list


def handle_doc_feedback_button(
    req: SocketModeRequest,
    client: TenantSocketModeClient,
) -> None:
    if not (actions := req.payload.get("actions")):
        logger.error("Missing actions. Unable to build the source feedback view")
        return

    # Extracts the feedback_id coming from the 'source feedback' button
    # and generates a new one for the View, to keep track of the doc info
    query_event_id, doc_id, doc_rank = decompose_action_id(actions[0].get("value"))
    external_id = build_feedback_id(query_event_id, doc_id, doc_rank)

    channel_id = req.payload["container"]["channel_id"]
    thread_ts = req.payload["container"].get("thread_ts", None)

    data = View(
        type="modal",
        callback_id=VIEW_DOC_FEEDBACK_ID,
        external_id=external_id,
        # We use the private metadata to keep track of the channel id and thread ts
        private_metadata=f"{channel_id}_{thread_ts}",
        title="Give Feedback",
        blocks=[get_document_feedback_blocks()],
        submit="send",
        close="cancel",
    )

    client.web_client.views_open(
        trigger_id=req.payload["trigger_id"], view=data.to_dict()
    )


def handle_generate_answer_button(
    req: SocketModeRequest,
    client: TenantSocketModeClient,
) -> None:
    channel_id = req.payload["channel"]["id"]
    channel_name = req.payload["channel"]["name"]
    message_ts = req.payload["message"]["ts"]
    thread_ts = req.payload["container"].get("thread_ts", None)
    user_id = req.payload["user"]["id"]
    expert_info = expert_info_from_slack_id(user_id, client.web_client, user_cache={})
    email = expert_info.email if expert_info else None

    if not thread_ts:
        raise ValueError("Missing thread_ts in the payload")

    thread_messages = read_slack_thread(
        tenant_id=client._tenant_id,
        channel=channel_id,
        thread=thread_ts,
        client=client.web_client,
    )
    # remove all assistant messages till we get to the last user message
    # we want the new answer to be generated off of the last "question" in
    # the thread
    for i in range(len(thread_messages) - 1, -1, -1):
        if thread_messages[i].role == MessageType.USER:
            break
        if thread_messages[i].role == MessageType.ASSISTANT:
            thread_messages.pop(i)

    # tell the user that we're working on it
    # Send an ephemeral message to the user that we're generating the answer
    respond_in_thread_or_channel(
        client=client.web_client,
        channel=channel_id,
        receiver_ids=[user_id],
        text="I'm working on generating a full answer for you. This may take a moment...",
        thread_ts=thread_ts,
    )

    with get_session_with_current_tenant() as db_session:
        slack_channel_config = get_slack_channel_config_for_bot_and_channel(
            db_session=db_session,
            slack_bot_id=client.slack_bot_id,
            channel_name=channel_name,
        )

        handle_regular_answer(
            message_info=SlackMessageInfo(
                thread_messages=thread_messages,
                channel_to_respond=channel_id,
                msg_to_respond=cast(str, message_ts or thread_ts),
                thread_to_respond=cast(str, thread_ts or message_ts),
                sender_id=user_id or None,
                email=email or None,
                bypass_filters=True,
                is_slash_command=False,
                is_bot_dm=False,
            ),
            slack_channel_config=slack_channel_config,
            receiver_ids=None,
            client=client.web_client,
            channel=channel_id,
            logger=logger,
            feedback_reminder_id=None,
        )


def handle_publish_ephemeral_message_button(
    req: SocketModeRequest,
    client: TenantSocketModeClient,
    action_id: str,
) -> None:
    """
    This function handles the Share with Everyone/Keep for Yourself buttons
    for ephemeral messages.
    """
    channel_id = req.payload["channel"]["id"]
    ephemeral_message_ts = req.payload["container"]["message_ts"]

    slack_sender_id = req.payload["user"]["id"]
    response_url = req.payload["response_url"]
    webhook = WebhookClient(url=response_url)

    # The additional data required that was added to buttons.
    # Specifically, this contains the message_info, channel_conf information
    # and some additional attributes.
    value_dict = json.loads(req.payload["actions"][0]["value"])

    original_question_ts = value_dict.get("original_question_ts")
    if not original_question_ts:
        raise ValueError("Missing original_question_ts in the payload")
    if not ephemeral_message_ts:
        raise ValueError("Missing ephemeral_message_ts in the payload")

    feedback_reminder_id = value_dict.get("feedback_reminder_id")

    slack_message_info = SlackMessageInfo(**value_dict["message_info"])
    channel_conf = value_dict.get("channel_conf")

    user_email = value_dict.get("message_info", {}).get("email")

    chat_message_id = value_dict.get("chat_message_id")

    # Obtain onyx_user and chat_message information
    if not chat_message_id:
        raise ValueError("Missing chat_message_id in the payload")

    with get_session_with_current_tenant() as db_session:
        onyx_user = get_user_by_email(user_email, db_session)
        if not onyx_user:
            raise ValueError("Cannot determine onyx_user_id from email in payload")
        try:
            chat_message = get_chat_message(chat_message_id, onyx_user.id, db_session)
        except ValueError:
            chat_message = get_chat_message(
                chat_message_id, None, db_session
            )  # is this good idea?
        except Exception as e:
            logger.error(f"Failed to get chat message: {e}")
            raise e

        chat_message_detail = translate_db_message_to_chat_message_detail(chat_message)

        # construct the proper citation format and then the answer in the suitable format
        # we need to construct the blocks.
        citation_list = _build_citation_list(chat_message_detail)

        onyx_bot_answer = ChatBasicResponse(
            answer=chat_message_detail.message,
            answer_citationless=remove_answer_citations(chat_message_detail.message),
            cited_documents={
                citation_info.citation_num: citation_info.document_id
                for citation_info in citation_list
            },
            top_documents=(
                chat_message_detail.context_docs.top_documents
                if chat_message_detail.context_docs
                else []
            ),
            message_id=chat_message_id,
            error_msg=None,
        )

    # Note: we need to use the webhook and the respond_url to update/delete ephemeral messages
    if action_id == SHOW_EVERYONE_ACTION_ID:
        # Convert to non-ephemeral message in thread
        try:
            webhook.send(
                response_type="ephemeral",
                text="",
                blocks=[],
                replace_original=True,
                delete_original=True,
            )
        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")

        # remove handling of empheremal block and add AI feedback.
        all_blocks = build_slack_response_blocks(
            answer=onyx_bot_answer,
            message_info=slack_message_info,
            channel_conf=channel_conf,
            use_citations=True,
            feedback_reminder_id=feedback_reminder_id,
            skip_ai_feedback=False,
            offer_ephemeral_publication=False,
            skip_restated_question=True,
        )
        try:
            # Post in thread as non-ephemeral message
            respond_in_thread_or_channel(
                client=client.web_client,
                channel=channel_id,
                receiver_ids=None,  # If respond_member_group_list is set, send to them. TODO: check!
                text="Hello! Onyx has some results for you!",
                blocks=all_blocks,
                thread_ts=original_question_ts,
                # don't unfurl, since otherwise we will have 5+ previews which makes the message very long
                unfurl=False,
                send_as_ephemeral=False,
            )
        except Exception as e:
            logger.error(f"Failed to publish ephemeral message: {e}")
            raise e

    elif action_id == KEEP_TO_YOURSELF_ACTION_ID:
        # Keep as ephemeral message in channel or thread, but remove the publish button and add feedback button

        changed_blocks = build_slack_response_blocks(
            answer=onyx_bot_answer,
            message_info=slack_message_info,
            channel_conf=channel_conf,
            use_citations=True,
            feedback_reminder_id=feedback_reminder_id,
            skip_ai_feedback=False,
            offer_ephemeral_publication=False,
            skip_restated_question=True,
        )

        try:
            if slack_message_info.thread_to_respond is not None:
                # There seems to be a bug in slack where an update within the thread
                # actually leads to the update to be posted in the channel. Therefore,
                # for now we delete the original ephemeral message and post a new one
                # if the ephemeral message is in a thread.
                webhook.send(
                    response_type="ephemeral",
                    text="",
                    blocks=[],
                    replace_original=True,
                    delete_original=True,
                )

                respond_in_thread_or_channel(
                    client=client.web_client,
                    channel=channel_id,
                    receiver_ids=[slack_sender_id],
                    text="Your personal response, sent as an ephemeral message.",
                    blocks=changed_blocks,
                    thread_ts=original_question_ts,
                    # don't unfurl, since otherwise we will have 5+ previews which makes the message very long
                    unfurl=False,
                    send_as_ephemeral=True,
                )
            else:
                # This works fine if the ephemeral message is in the channel
                webhook.send(
                    response_type="ephemeral",
                    text="Your personal response, sent as an ephemeral message.",
                    blocks=changed_blocks,
                    replace_original=True,
                    delete_original=False,
                )
        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")


def handle_slack_feedback(
    feedback_id: str,
    feedback_type: str,
    feedback_msg_reminder: str,
    client: WebClient,
    user_id_to_post_confirmation: str,
    channel_id_to_post_confirmation: str,
    thread_ts_to_post_confirmation: str,
) -> None:
    message_id, doc_id, doc_rank = decompose_action_id(feedback_id)

    # Get Onyx user from Slack ID
    expert_info = expert_info_from_slack_id(
        user_id_to_post_confirmation, client, user_cache={}
    )
    email = expert_info.email if expert_info else None

    with get_session_with_current_tenant() as db_session:
        onyx_user = get_user_by_email(email, db_session) if email else None
        if feedback_type in [LIKE_BLOCK_ACTION_ID, DISLIKE_BLOCK_ACTION_ID]:
            create_chat_message_feedback(
                is_positive=feedback_type == LIKE_BLOCK_ACTION_ID,
                feedback_text="",
                chat_message_id=message_id,
                user_id=onyx_user.id if onyx_user else None,
                db_session=db_session,
            )
            remove_scheduled_feedback_reminder(
                client=client,
                channel=user_id_to_post_confirmation,
                msg_id=feedback_msg_reminder,
            )
        elif feedback_type in [
            SearchFeedbackType.ENDORSE.value,
            SearchFeedbackType.REJECT.value,
            SearchFeedbackType.HIDE.value,
        ]:
            if doc_id is None or doc_rank is None:
                raise ValueError("Missing information for Document Feedback")

            if feedback_type == SearchFeedbackType.ENDORSE.value:
                feedback = SearchFeedbackType.ENDORSE
            elif feedback_type == SearchFeedbackType.REJECT.value:
                feedback = SearchFeedbackType.REJECT
            else:
                feedback = SearchFeedbackType.HIDE

            create_doc_retrieval_feedback(
                message_id=message_id,
                document_id=doc_id,
                document_rank=doc_rank,
                db_session=db_session,
                clicked=False,  # Not tracking this for Slack
                feedback=feedback,
            )
        else:
            logger.error(f"Feedback type '{feedback_type}' not supported")

    if get_feedback_visibility() == FeedbackVisibility.PRIVATE or feedback_type not in [
        LIKE_BLOCK_ACTION_ID,
        DISLIKE_BLOCK_ACTION_ID,
    ]:
        client.chat_postEphemeral(
            channel=channel_id_to_post_confirmation,
            user=user_id_to_post_confirmation,
            thread_ts=thread_ts_to_post_confirmation,
            text="Thanks for your feedback!",
        )
    else:
        feedback_response_txt = (
            "liked" if feedback_type == LIKE_BLOCK_ACTION_ID else "disliked"
        )

        if get_feedback_visibility() == FeedbackVisibility.ANONYMOUS:
            msg = f"A user has {feedback_response_txt} the AI Answer"
        else:
            msg = f"<@{user_id_to_post_confirmation}> has {feedback_response_txt} the AI Answer"

        respond_in_thread_or_channel(
            client=client,
            channel=channel_id_to_post_confirmation,
            text=msg,
            thread_ts=thread_ts_to_post_confirmation,
            unfurl=False,
        )


def handle_followup_button(
    req: SocketModeRequest,
    client: TenantSocketModeClient,
) -> None:
    action_id = None
    if actions := req.payload.get("actions"):
        action = cast(dict[str, Any], actions[0])
        action_id = cast(str, action.get("block_id"))

    channel_id = req.payload["container"]["channel_id"]
    thread_ts = req.payload["container"].get("thread_ts", None)

    update_emote_react(
        emoji=ONYX_BOT_FOLLOWUP_EMOJI,
        channel=channel_id,
        message_ts=thread_ts,
        remove=False,
        client=client.web_client,
    )

    tag_ids: list[str] = []
    group_ids: list[str] = []
    with get_session_with_current_tenant() as db_session:
        channel_name, is_dm = get_channel_name_from_id(
            client=client.web_client, channel_id=channel_id
        )
        slack_channel_config = get_slack_channel_config_for_bot_and_channel(
            db_session=db_session,
            slack_bot_id=client.slack_bot_id,
            channel_name=channel_name,
        )
        if slack_channel_config:
            tag_names = slack_channel_config.channel_config.get("follow_up_tags")
            remaining = None
            if tag_names:
                tag_ids, remaining = fetch_slack_user_ids_from_emails(
                    tag_names, client.web_client
                )
            if remaining:
                group_ids, _ = fetch_group_ids_from_names(remaining, client.web_client)

    blocks = build_follow_up_resolved_blocks(tag_ids=tag_ids, group_ids=group_ids)

    respond_in_thread_or_channel(
        client=client.web_client,
        channel=channel_id,
        text="Received your request for more help",
        blocks=blocks,
        thread_ts=thread_ts,
        unfurl=False,
    )

    if action_id is not None:
        message_id, _, _ = decompose_action_id(action_id)

        create_chat_message_feedback(
            is_positive=None,
            feedback_text="",
            chat_message_id=message_id,
            user_id=None,  # no "user" for Slack bot for now
            db_session=db_session,
            required_followup=True,
        )


def get_clicker_name(
    req: SocketModeRequest,
    client: TenantSocketModeClient,
) -> str:
    clicker_name = req.payload.get("user", {}).get("name", "Someone")
    clicker_real_name = None
    try:
        clicker = client.web_client.users_info(user=req.payload["user"]["id"])
        clicker_real_name = (
            cast(dict, clicker.data).get("user", {}).get("profile", {}).get("real_name")
        )
    except Exception:
        # Likely a scope issue
        pass

    if clicker_real_name:
        clicker_name = clicker_real_name

    return clicker_name


def handle_followup_resolved_button(
    req: SocketModeRequest,
    client: TenantSocketModeClient,
    immediate: bool = False,
) -> None:
    channel_id = req.payload["container"]["channel_id"]
    message_ts = req.payload["container"]["message_ts"]
    thread_ts = req.payload["container"].get("thread_ts", None)

    clicker_name = get_clicker_name(req, client)

    update_emote_react(
        emoji=ONYX_BOT_FOLLOWUP_EMOJI,
        channel=channel_id,
        message_ts=thread_ts,
        remove=True,
        client=client.web_client,
    )

    # Delete the message with the option to mark resolved
    if not immediate:
        response = client.web_client.chat_delete(
            channel=channel_id,
            ts=message_ts,
        )

        if not response.get("ok"):
            logger.error("Unable to delete message for resolved")

    if immediate:
        msg_text = f"{clicker_name} has marked this question as resolved!"
    else:
        msg_text = (
            f"{clicker_name} has marked this question as resolved! "
            f'\n\n You can always click the "I need more help button" to let the team '
            f"know that your problem still needs attention."
        )

    resolved_block = SectionBlock(text=msg_text)

    respond_in_thread_or_channel(
        client=client.web_client,
        channel=channel_id,
        text="Your request for help as been addressed!",
        blocks=[resolved_block],
        thread_ts=thread_ts,
        unfurl=False,
    )
