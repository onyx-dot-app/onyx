import functools
from collections.abc import Callable
from typing import Any
from typing import Optional
from typing import TypeVar

from retry import retry
from slack_sdk import WebClient
from slack_sdk.models.blocks import SectionBlock

from onyx.chat.chat_utils import prepare_chat_message_request
from onyx.chat.models import ChatOnyxBotResponse
from onyx.chat.process_message import gather_stream_for_slack
from onyx.chat.process_message import stream_chat_message_objects
from onyx.configs.app_configs import DISABLE_GENERATIVE_AI
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.configs.onyxbot_configs import DANSWER_BOT_DISABLE_DOCS_ONLY_ANSWER
from onyx.configs.onyxbot_configs import DANSWER_BOT_DISPLAY_ERROR_MSGS
from onyx.configs.onyxbot_configs import DANSWER_BOT_NUM_RETRIES
from onyx.configs.onyxbot_configs import DANSWER_FOLLOWUP_EMOJI
from onyx.configs.onyxbot_configs import DANSWER_REACT_EMOJI
from onyx.configs.onyxbot_configs import MAX_THREAD_CONTEXT_PERCENTAGE
from onyx.context.search.enums import OptionalSearchSetting
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import RetrievalDetails
from onyx.db.engine import get_session_with_tenant
from onyx.db.models import SlackChannelConfig
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.db.users import get_user_by_email
from onyx.onyxbot.slack.blocks import build_slack_response_blocks
from onyx.onyxbot.slack.handlers.utils import send_team_member_message
from onyx.onyxbot.slack.handlers.utils import slackify_message_thread
from onyx.onyxbot.slack.models import SlackMessageInfo
from onyx.onyxbot.slack.utils import respond_in_thread
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
    slack_channel_config: SlackChannelConfig | None,
    receiver_ids: list[str] | None,
    client: WebClient,
    channel: str,
    logger: OnyxLoggingAdapter,
    feedback_reminder_id: str | None,
    tenant_id: str | None,
    num_retries: int = DANSWER_BOT_NUM_RETRIES,
    thread_context_percent: float = MAX_THREAD_CONTEXT_PERCENTAGE,
    should_respond_with_error_msgs: bool = DANSWER_BOT_DISPLAY_ERROR_MSGS,
    disable_docs_only_answer: bool = DANSWER_BOT_DISABLE_DOCS_ONLY_ANSWER,
) -> bool:
    channel_conf = slack_channel_config.channel_config if slack_channel_config else None

    messages = message_info.thread_messages

    message_ts_to_respond_to = message_info.msg_to_respond
    is_bot_msg = message_info.is_bot_msg
    user = None
    if message_info.is_bot_dm:
        if message_info.email:
            with get_session_with_tenant(tenant_id) as db_session:
                user = get_user_by_email(message_info.email, db_session)

    document_set_names: list[str] | None = None
    prompt = None
    # If no persona is specified, use the default search based persona
    # This way slack flow always has a persona
    persona = slack_channel_config.persona if slack_channel_config else None
    if not persona:
        with get_session_with_tenant(tenant_id) as db_session:
            persona = get_persona_by_id(DEFAULT_PERSONA_ID, user, db_session)
            document_set_names = [
                document_set.name for document_set in persona.document_sets
            ]
            prompt = persona.prompts[0] if persona.prompts else None
    else:
        document_set_names = [
            document_set.name for document_set in persona.document_sets
        ]
        prompt = persona.prompts[0] if persona.prompts else None

    should_respond_even_with_no_docs = persona.num_chunks == 0 if persona else False

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

    combined_message = slackify_message_thread(messages)

    bypass_acl = False
    if (
        slack_channel_config
        and slack_channel_config.persona
        and slack_channel_config.persona.document_sets
    ):
        # For Slack channels, use the full document set, admin will be warned when configuring it
        # with non-public document sets
        bypass_acl = True

    if not message_ts_to_respond_to and not is_bot_msg:
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
        new_message_request: CreateChatMessageRequest, onyx_user: User | None
    ) -> ChatOnyxBotResponse:
        with get_session_with_tenant(tenant_id) as db_session:
            packets = stream_chat_message_objects(
                new_msg_req=new_message_request,
                user=onyx_user,
                db_session=db_session,
                bypass_acl=bypass_acl,
            )

            answer = gather_stream_for_slack(packets)

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
        auto_detect_filters = (
            slack_channel_config.enable_auto_filters
            if slack_channel_config is not None
            else False
        )
        retrieval_details = RetrievalDetails(
            run_search=OptionalSearchSetting.ALWAYS,
            real_time=False,
            filters=filters,
            enable_auto_detect_filters=auto_detect_filters,
        )

        with get_session_with_tenant(tenant_id) as db_session:
            answer_request = prepare_chat_message_request(
                message_text=combined_message,
                user=user,
                persona_id=persona.id,
                # This is not used in the Slack flow, only in the answer API
                persona_override_config=None,
                prompt=prompt,
                message_ts_to_respond_to=message_ts_to_respond_to,
                retrieval_details=retrieval_details,
                rerank_settings=None,  # Rerank customization supported in Slack flow
                db_session=db_session,
            )

        answer = _get_slack_answer(new_message_request=answer_request, onyx_user=user)

    except Exception as e:
        logger.exception(
            f"Unable to process message - did not successfully answer "
            f"in {num_retries} attempts"
        )
        # Optionally, respond in thread with the error message, Used primarily
        # for debugging purposes
        if should_respond_with_error_msgs:
            respond_in_thread(
                client=client,
                channel=channel,
                receiver_ids=None,
                text=f"Encountered exception when trying to answer: \n\n```{e}```",
                thread_ts=message_ts_to_respond_to,
            )

        # In case of failures, don't keep the reaction there permanently
        update_emote_react(
            emoji=DANSWER_REACT_EMOJI,
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
            respond_in_thread(
                client=client,
                channel=channel,
                receiver_ids=receiver_ids,
                text="Hello! Onyx has some results for you!",
                blocks=[
                    SectionBlock(
                        text="Onyx is down for maintenance.\nWe're working hard on recharging the AI!"
                    )
                ],
                thread_ts=message_ts_to_respond_to,
                # don't unfurl, since otherwise we will have 5+ previews which makes the message very long
                unfurl=False,
            )

            # For DM (ephemeral message), we need to create a thread via a normal message so the user can see
            # the ephemeral message. This also will give the user a notification which ephemeral message does not.
            if receiver_ids:
                respond_in_thread(
                    client=client,
                    channel=channel,
                    text=(
                        "👋 Hi, we've just gathered and forwarded the relevant "
                        + "information to the team. They'll get back to you shortly!"
                    ),
                    thread_ts=message_ts_to_respond_to,
                )

            return False

        except Exception:
            logger.exception(
                f"Unable to process message - could not respond in slack in {num_retries} attempts"
            )
            return True

    # Got an answer at this point, can remove reaction and give results
    update_emote_react(
        emoji=DANSWER_REACT_EMOJI,
        channel=message_info.channel_to_respond,
        message_ts=message_info.msg_to_respond,
        remove=True,
        client=client,
    )

    if answer.answer_valid is False:
        logger.notice(
            "Answer was evaluated to be invalid, throwing it away without responding."
        )
        update_emote_react(
            emoji=DANSWER_FOLLOWUP_EMOJI,
            channel=message_info.channel_to_respond,
            message_ts=message_info.msg_to_respond,
            remove=False,
            client=client,
        )

        if answer.answer:
            logger.debug(answer.answer)
        return True

    retrieval_info = answer.docs
    if not retrieval_info:
        # This should not happen, even with no docs retrieved, there is still info returned
        raise RuntimeError("Failed to retrieve docs, cannot answer question.")

    top_docs = retrieval_info.top_documents
    if not top_docs and not should_respond_even_with_no_docs:
        logger.error(
            f"Unable to answer question: '{combined_message}' - no documents found"
        )
        # Optionally, respond in thread with the error message
        # Used primarily for debugging purposes
        if should_respond_with_error_msgs:
            respond_in_thread(
                client=client,
                channel=channel,
                receiver_ids=None,
                text="Found no documents when trying to answer. Did you index any documents?",
                thread_ts=message_ts_to_respond_to,
            )
        return True

    if not answer.answer and disable_docs_only_answer:
        logger.notice(
            "Unable to find answer - not responding since the "
            "`DANSWER_BOT_DISABLE_DOCS_ONLY_ANSWER` env variable is set"
        )
        return True

    only_respond_if_citations = (
        channel_conf
        and "well_answered_postfilter" in channel_conf.get("answer_filters", [])
    )

    if (
        only_respond_if_citations
        and not answer.citations
        and not message_info.bypass_filters
    ):
        logger.error(
            f"Unable to find citations to answer: '{answer.answer}' - not answering!"
        )
        # Optionally, respond in thread with the error message
        # Used primarily for debugging purposes
        if should_respond_with_error_msgs:
            respond_in_thread(
                client=client,
                channel=channel,
                receiver_ids=None,
                text="Found no citations or quotes when trying to answer.",
                thread_ts=message_ts_to_respond_to,
            )
        return True

    all_blocks = build_slack_response_blocks(
        tenant_id=tenant_id,
        message_info=message_info,
        answer=answer,
        channel_conf=channel_conf,
        use_citations=True,  # No longer supporting quotes
        feedback_reminder_id=feedback_reminder_id,
    )

    try:
        respond_in_thread(
            client=client,
            channel=channel,
            receiver_ids=[message_info.sender]
            if message_info.is_bot_msg and message_info.sender
            else receiver_ids,
            text="Hello! Onyx has some results for you!",
            blocks=all_blocks,
            thread_ts=message_ts_to_respond_to,
            # don't unfurl, since otherwise we will have 5+ previews which makes the message very long
            unfurl=False,
        )

        # For DM (ephemeral message), we need to create a thread via a normal message so the user can see
        # the ephemeral message. This also will give the user a notification which ephemeral message does not.
        # if there is no message_ts_to_respond_to, and we have made it this far, then this is a /onyx message
        # so we shouldn't send_team_member_message
        if receiver_ids and message_ts_to_respond_to is not None:
            send_team_member_message(
                client=client,
                channel=channel,
                thread_ts=message_ts_to_respond_to,
            )

        return False

    except Exception:
        logger.exception(
            f"Unable to process message - could not respond in slack in {num_retries} attempts"
        )
        return True
