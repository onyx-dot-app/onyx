import functools
from collections.abc import Callable
from typing import Any
from typing import Optional
from typing import TypeVar

from retry import retry
from slack_sdk import WebClient
from slack_sdk.models.blocks import SectionBlock

from onyx.chat.chat_utils import prepare_chat_message_request
from onyx.chat.models import ChatBasicResponse
from onyx.chat.process_message import gather_stream
from onyx.chat.process_message import stream_chat_message_objects
from onyx.configs.app_configs import DISABLE_GENERATIVE_AI
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.configs.onyxbot_configs import MAX_THREAD_CONTEXT_PERCENTAGE
from onyx.configs.onyxbot_configs import ONYX_BOT_DISABLE_DOCS_ONLY_ANSWER
from onyx.configs.onyxbot_configs import ONYX_BOT_DISPLAY_ERROR_MSGS
from onyx.configs.onyxbot_configs import ONYX_BOT_NUM_RETRIES
from onyx.configs.onyxbot_configs import ONYX_BOT_REACT_EMOJI
from onyx.context.search.enums import OptionalSearchSetting
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import RetrievalDetails
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import SlackChannelConfig
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.db.persona import persona_has_search_tool
from onyx.db.users import get_user_by_email
from onyx.onyxbot.slack.blocks import build_slack_response_blocks
from onyx.onyxbot.slack.handlers.utils import send_team_member_message
from onyx.onyxbot.slack.handlers.utils import slackify_message_thread
from onyx.onyxbot.slack.models import SlackMessageInfo
from onyx.onyxbot.slack.utils import respond_in_thread_or_channel
from onyx.onyxbot.slack.utils import SlackRateLimiter
from onyx.onyxbot.slack.utils import update_emote_react
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from onyx.utils.logger import OnyxLoggingAdapter

srl = SlackRateLimiter()

RT = TypeVar("RT")  # return type


def rate_limits(
    client: WebClient, channel: str, thread_ts: Optional[str]
) -> Callable[[Callable[..., RT]], Callable[..., RT]]:
    def decorator(func: Callable[..., RT]) -> Callable[..., RT]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> RT:
            if not srl.is_available():
                func_randid, position = srl.init_waiter()
                srl.notify(client, channel, position, thread_ts)
                while not srl.is_available():
                    srl.waiter(func_randid)
            srl.acquire_slot()
            return func(*args, **kwargs)

        return wrapper

    return decorator


def handle_regular_answer(
    message_info: SlackMessageInfo,
    slack_channel_config: SlackChannelConfig,
    receiver_ids: list[str] | None,
    client: WebClient,
    channel: str,
    logger: OnyxLoggingAdapter,
    feedback_reminder_id: str | None,
    num_retries: int = ONYX_BOT_NUM_RETRIES,
    thread_context_percent: float = MAX_THREAD_CONTEXT_PERCENTAGE,
    should_respond_with_error_msgs: bool = ONYX_BOT_DISPLAY_ERROR_MSGS,
    disable_docs_only_answer: bool = ONYX_BOT_DISABLE_DOCS_ONLY_ANSWER,
) -> bool:
    channel_conf = slack_channel_config.channel_config

    messages = message_info.thread_messages

    message_ts_to_respond_to = message_info.msg_to_respond
    is_slash_command = message_info.is_slash_command

    # Capture whether response mode for channel is ephemeral. Even if the channel is set
    # to respond with an ephemeral message, we still send as non-ephemeral if
    # the message is a dm with the Onyx bot.
    send_as_ephemeral = (
        slack_channel_config.channel_config.get("is_ephemeral", False)
        or message_info.is_slash_command
    ) and not message_info.is_bot_dm

    # If the channel mis configured to respond with an ephemeral message,
    # or the message is a dm to the Onyx bot, we should use the proper onyx user from the email.
    # This will make documents privately accessible to the user available to Onyx Bot answers.
    # Otherwise - if not ephemeral or DM to Onyx Bot - we must use None as the user to restrict
    # to public docs.

    user = None
    if message_info.email:
        with get_session_with_current_tenant() as db_session:
            user = get_user_by_email(message_info.email, db_session)

    target_thread_ts = (
        None
        if send_as_ephemeral and len(message_info.thread_messages) < 2
        else message_ts_to_respond_to
    )
    target_receiver_ids = (
        [message_info.sender_id]
        if message_info.sender_id and send_as_ephemeral
        else receiver_ids
    )

    document_set_names: list[str] | None = None
    # If no persona is specified, use the default search based persona
    # This way slack flow always has a persona
    persona = slack_channel_config.persona
    if not persona:
        with get_session_with_current_tenant() as db_session:
            persona = get_persona_by_id(DEFAULT_PERSONA_ID, user, db_session)
            document_set_names = [
                document_set.name for document_set in persona.document_sets
            ]
    else:
        document_set_names = [
            document_set.name for document_set in persona.document_sets
        ]

    with get_session_with_current_tenant() as db_session:
        expecting_search_result = persona_has_search_tool(persona.id, db_session)

    # TODO: Add in support for Slack to truncate messages based on max LLM context
    # llm, _ = get_llms_for_persona(persona)

    # llm_tokenizer = get_tokenizer(
    #     model_name=llm.config.model_name,
    #     provider_type=llm.config.model_provider,
    # )

    # # In cases of threads, split the available tokens between docs and thread context
    # input_tokens = get_max_input_tokens(
    #     model_name=llm.config.model_name,
    #     model_provider=llm.config.model_provider,
    # )
    # max_history_tokens = int(input_tokens * thread_context_percent)
    # combined_message = combine_message_thread(
    #     messages, max_tokens=max_history_tokens, llm_tokenizer=llm_tokenizer
    # )

    # NOTE: only the message history will contain the person asking. This is likely
    # fine since the most common use case for this info is when referring to a user
    # who previously posted in the thread.
    user_message = messages[-1]
    history_messages = messages[:-1]
    single_message_history = slackify_message_thread(history_messages) or None

    # Always check for ACL permissions, also for documnt sets that were explicitly added
    # to the Bot by the Administrator. (Change relative to earlier behavior where all documents
    # in an attached document set were available to all users in the channel.)
    bypass_acl = False

    if not message_ts_to_respond_to and not is_slash_command:
        # if the message is not "/onyx" command, then it should have a message ts to respond to
        raise RuntimeError(
            "No message timestamp to respond to in `handle_message`. This should never happen."
        )

    @retry(
        tries=num_retries,
        delay=0.25,
        backoff=2,
    )
    @rate_limits(client=client, channel=channel, thread_ts=message_ts_to_respond_to)
    def _get_slack_answer(
        new_message_request: CreateChatMessageRequest,
        # pass in `None` to make the answer based on public documents only
        onyx_user: User | None,
    ) -> ChatBasicResponse:
        with get_session_with_current_tenant() as db_session:
            packets = stream_chat_message_objects(
                new_msg_req=new_message_request,
                user=onyx_user,
                db_session=db_session,
                bypass_acl=bypass_acl,
                single_message_history=single_message_history,
            )
            answer = gather_stream(packets)

        if answer.error_msg:
            raise RuntimeError(answer.error_msg)

        return answer

    try:
        # By leaving time_cutoff and favor_recent as None, and setting enable_auto_detect_filters
        # it allows the slack flow to extract out filters from the user query
        filters = BaseFilters(
            source_type=None,
            document_set=document_set_names,
            time_cutoff=None,
        )

        # Default True because no other ways to apply filters in Slack (no nice UI)
        # Commenting this out because this is only available to the slackbot for now
        # later we plan to implement this at the persona level where this will get
        # commented back in
        # auto_detect_filters = (
        #     persona.llm_filter_extraction if persona is not None else True
        # )
        auto_detect_filters = slack_channel_config.enable_auto_filters
        retrieval_details = RetrievalDetails(
            run_search=OptionalSearchSetting.ALWAYS,
            real_time=False,
            filters=filters,
            enable_auto_detect_filters=auto_detect_filters,
        )

        with get_session_with_current_tenant() as db_session:
            answer_request = prepare_chat_message_request(
                message_text=user_message.message,
                user=user,
                persona_id=persona.id,
                # This is not used in the Slack flow, only in the answer API
                persona_override_config=None,
                message_ts_to_respond_to=message_ts_to_respond_to,
                retrieval_details=retrieval_details,
                rerank_settings=None,  # Rerank customization supported in Slack flow
                db_session=db_session,
                slack_context=message_info.slack_context,  # Pass Slack context from message_info
            )

        # if it's a DM or ephemeral message, answer based on private documents.
        # otherwise, answer based on public documents ONLY as to not leak information.
        can_search_over_private_docs = message_info.is_bot_dm or send_as_ephemeral
        answer = _get_slack_answer(
            new_message_request=answer_request,
            onyx_user=user if can_search_over_private_docs else None,
        )

    except Exception as e:
        logger.exception(
            f"Unable to process message - did not successfully answer "
            f"in {num_retries} attempts"
        )
        # Optionally, respond in thread with the error message, Used primarily
        # for debugging purposes
        if should_respond_with_error_msgs:
            respond_in_thread_or_channel(
                client=client,
                channel=channel,
                receiver_ids=target_receiver_ids,
                text=f"Encountered exception when trying to answer: \n\n```{e}```",
                thread_ts=target_thread_ts,
                send_as_ephemeral=send_as_ephemeral,
            )

        # In case of failures, don't keep the reaction there permanently
        update_emote_react(
            emoji=ONYX_BOT_REACT_EMOJI,
            channel=message_info.channel_to_respond,
            message_ts=message_info.msg_to_respond,
            remove=True,
            client=client,
        )

        return True

    # Edge case handling, for tracking down the Slack usage issue
    if answer is None:
        assert DISABLE_GENERATIVE_AI is True
        try:
            respond_in_thread_or_channel(
                client=client,
                channel=channel,
                receiver_ids=target_receiver_ids,
                text="Hello! Onyx has some results for you!",
                blocks=[
                    SectionBlock(
                        text="Onyx is down for maintenance.\nWe're working hard on recharging the AI!"
                    )
                ],
                thread_ts=target_thread_ts,
                send_as_ephemeral=send_as_ephemeral,
                # don't unfurl, since otherwise we will have 5+ previews which makes the message very long
                unfurl=False,
            )

            # For DM (ephemeral message), we need to create a thread via a normal message so the user can see
            # the ephemeral message. This also will give the user a notification which ephemeral message does not.

            # If the channel is ephemeral, we don't need to send a message to the user since they will already see the message
            if target_receiver_ids and not send_as_ephemeral:
                respond_in_thread_or_channel(
                    client=client,
                    channel=channel,
                    text=(
                        "👋 Hi, we've just gathered and forwarded the relevant "
                        + "information to the team. They'll get back to you shortly!"
                    ),
                    thread_ts=target_thread_ts,
                    send_as_ephemeral=send_as_ephemeral,
                )

            return False

        except Exception:
            logger.exception(
                f"Unable to process message - could not respond in slack in {num_retries} attempts"
            )
            return True

    # Got an answer at this point, can remove reaction and give results
    if not is_slash_command:  # Slash commands don't have reactions
        update_emote_react(
            emoji=ONYX_BOT_REACT_EMOJI,
            channel=message_info.channel_to_respond,
            message_ts=message_info.msg_to_respond,
            remove=True,
            client=client,
        )

    top_docs = answer.top_documents
    if not top_docs and expecting_search_result:
        logger.error(
            f"Unable to answer question: '{user_message}' - no documents found"
        )
        # Optionally, respond in thread with the error message
        # Used primarily for debugging purposes
        if should_respond_with_error_msgs:
            respond_in_thread_or_channel(
                client=client,
                channel=channel,
                receiver_ids=target_receiver_ids,
                text="Found no documents when trying to answer. Did you index any documents?",
                thread_ts=target_thread_ts,
                send_as_ephemeral=send_as_ephemeral,
            )
        return True

    if not answer.answer and disable_docs_only_answer:
        logger.notice(
            "Unable to find answer - not responding since the "
            "`ONYX_BOT_DISABLE_DOCS_ONLY_ANSWER` env variable is set"
        )
        return True

    only_respond_if_citations = (
        channel_conf
        and "well_answered_postfilter" in channel_conf.get("answer_filters", [])
    )

    if (
        expecting_search_result
        and only_respond_if_citations
        and not answer.cited_documents
        and not message_info.bypass_filters
    ):
        logger.error(
            f"Unable to find citations to answer: '{answer.answer}' - not answering!"
        )
        # Optionally, respond in thread with the error message
        # Used primarily for debugging purposes
        if should_respond_with_error_msgs:
            respond_in_thread_or_channel(
                client=client,
                channel=channel,
                receiver_ids=target_receiver_ids,
                text="Found no citations or quotes when trying to answer.",
                thread_ts=target_thread_ts,
                send_as_ephemeral=send_as_ephemeral,
            )
        return True

    if (
        send_as_ephemeral
        and target_receiver_ids is not None
        and len(target_receiver_ids) == 1
    ):
        offer_ephemeral_publication = True
        skip_ai_feedback = True
    else:
        offer_ephemeral_publication = False
        skip_ai_feedback = False

    all_blocks = build_slack_response_blocks(
        message_info=message_info,
        answer=answer,
        channel_conf=channel_conf,
        use_citations=True,  # No longer supporting quotes
        feedback_reminder_id=feedback_reminder_id,
        expecting_search_result=expecting_search_result,
        offer_ephemeral_publication=offer_ephemeral_publication,
        skip_ai_feedback=skip_ai_feedback,
    )

    # NOTE(rkuo): Slack has a maximum block list size of 50.
    # we should modify build_slack_response_blocks to respect the max
    # but enforcing the hard limit here is the last resort.
    all_blocks = all_blocks[:50]

    try:
        respond_in_thread_or_channel(
            client=client,
            channel=channel,
            receiver_ids=target_receiver_ids,
            text="Hello! Onyx has some results for you!",
            blocks=all_blocks,
            thread_ts=target_thread_ts,
            # don't unfurl, since otherwise we will have 5+ previews which makes the message very long
            unfurl=False,
            send_as_ephemeral=send_as_ephemeral,
        )

        # For DM (ephemeral message), we need to create a thread via a normal message so the user can see
        # the ephemeral message. This also will give the user a notification which ephemeral message does not.
        # if there is no message_ts_to_respond_to, and we have made it this far, then this is a /onyx message
        # so we shouldn't send_team_member_message
        if (
            target_receiver_ids
            and message_ts_to_respond_to is not None
            and not send_as_ephemeral
            and target_thread_ts is not None
        ):
            send_team_member_message(
                client=client,
                channel=channel,
                thread_ts=target_thread_ts,
                receiver_ids=target_receiver_ids,
                send_as_ephemeral=send_as_ephemeral,
            )

        return False

    except Exception:
        logger.exception(
            f"Unable to process message - could not respond in slack in {num_retries} attempts"
        )
        return True
