import functools
import logging
from collections.abc import Callable
from typing import Any
from typing import cast
from typing import Optional
from typing import TypeVar

from retry import retry
from slack_sdk import WebClient
from slack_sdk.models.blocks import DividerBlock
from slack_sdk.models.blocks import SectionBlock
from sqlalchemy.orm import Session

from danswer.configs.app_configs import DISABLE_GENERATIVE_AI
from danswer.configs.danswerbot_configs import DANSWER_BOT_ANSWER_GENERATION_TIMEOUT
from danswer.configs.danswerbot_configs import DANSWER_BOT_DISABLE_COT
from danswer.configs.danswerbot_configs import DANSWER_BOT_DISABLE_DOCS_ONLY_ANSWER
from danswer.configs.danswerbot_configs import DANSWER_BOT_DISPLAY_ERROR_MSGS
from danswer.configs.danswerbot_configs import DANSWER_BOT_NUM_RETRIES
from danswer.configs.danswerbot_configs import DANSWER_BOT_TARGET_CHUNK_PERCENTAGE
from danswer.configs.danswerbot_configs import DANSWER_BOT_USE_QUOTES
from danswer.configs.danswerbot_configs import DANSWER_FOLLOWUP_EMOJI
from danswer.configs.danswerbot_configs import DANSWER_REACT_EMOJI
from danswer.configs.danswerbot_configs import ENABLE_DANSWERBOT_REFLEXION
from danswer.danswerbot.slack.blocks import build_documents_blocks
from danswer.danswerbot.slack.blocks import build_follow_up_block
from danswer.danswerbot.slack.blocks import build_qa_response_blocks
from danswer.danswerbot.slack.blocks import build_sources_blocks
from danswer.danswerbot.slack.blocks import get_restate_blocks
from danswer.danswerbot.slack.handlers.utils import send_team_member_message
from danswer.danswerbot.slack.models import SlackMessageInfo
from danswer.danswerbot.slack.utils import respond_in_thread
from danswer.danswerbot.slack.utils import SlackRateLimiter
from danswer.danswerbot.slack.utils import update_emote_react
from danswer.db.engine import get_sqlalchemy_engine
from danswer.db.models import Persona
from danswer.db.models import SlackBotConfig
from danswer.db.models import SlackBotResponseType
from danswer.db.persona import fetch_persona_by_id
from danswer.llm.answering.prompts.citations_prompt import (
    compute_max_document_tokens_for_persona,
)
from danswer.llm.factory import get_llms_for_persona
from danswer.llm.utils import check_number_of_tokens
from danswer.llm.utils import get_max_input_tokens
from danswer.one_shot_answer.answer_question import get_search_answer
from danswer.one_shot_answer.models import DirectQARequest
from danswer.one_shot_answer.models import OneShotQAResponse
from danswer.search.enums import OptionalSearchSetting
from danswer.search.models import BaseFilters
from danswer.search.models import RetrievalDetails
from shared_configs.configs import ENABLE_RERANKING_ASYNC_FLOW


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
    slack_bot_config: SlackBotConfig | None,
    receiver_ids: list[str] | None,
    client: WebClient,
    channel: str,
    logger: logging.Logger,
    feedback_reminder_id: str | None,
    num_retries: int = DANSWER_BOT_NUM_RETRIES,
    answer_generation_timeout: int = DANSWER_BOT_ANSWER_GENERATION_TIMEOUT,
    thread_context_percent: float = DANSWER_BOT_TARGET_CHUNK_PERCENTAGE,
    should_respond_with_error_msgs: bool = DANSWER_BOT_DISPLAY_ERROR_MSGS,
    disable_docs_only_answer: bool = DANSWER_BOT_DISABLE_DOCS_ONLY_ANSWER,
    disable_cot: bool = DANSWER_BOT_DISABLE_COT,
    reflexion: bool = ENABLE_DANSWERBOT_REFLEXION,
) -> bool:
    channel_conf = slack_bot_config.channel_config if slack_bot_config else None

    messages = message_info.thread_messages
    message_ts_to_respond_to = message_info.msg_to_respond
    is_bot_msg = message_info.is_bot_msg

    document_set_names: list[str] | None = None
    persona = slack_bot_config.persona if slack_bot_config else None
    prompt = None
    if persona:
        document_set_names = [
            document_set.name for document_set in persona.document_sets
        ]
        prompt = persona.prompts[0] if persona.prompts else None

    should_respond_even_with_no_docs = persona.num_chunks == 0 if persona else False

    bypass_acl = False
    if (
        slack_bot_config
        and slack_bot_config.persona
        and slack_bot_config.persona.document_sets
    ):
        # For Slack channels, use the full document set, admin will be warned when configuring it
        # with non-public document sets
        bypass_acl = True

    # figure out if we want to use citations or quotes
    use_citations = (
        not DANSWER_BOT_USE_QUOTES
        if slack_bot_config is None
        else slack_bot_config.response_type == SlackBotResponseType.CITATIONS
    )

    if not message_ts_to_respond_to:
        raise RuntimeError(
            "No message timestamp to respond to in `handle_message`. This should never happen."
        )

    @retry(
        tries=num_retries,
        delay=0.25,
        backoff=2,
        logger=logger,
    )
    @rate_limits(client=client, channel=channel, thread_ts=message_ts_to_respond_to)
    def _get_answer(new_message_request: DirectQARequest) -> OneShotQAResponse | None:
        max_document_tokens: int | None = None
        max_history_tokens: int | None = None

        with Session(get_sqlalchemy_engine()) as db_session:
            if len(new_message_request.messages) > 1:
                persona = cast(
                    Persona,
                    fetch_persona_by_id(db_session, new_message_request.persona_id),
                )
                llm, _ = get_llms_for_persona(persona)

                # In cases of threads, split the available tokens between docs and thread context
                input_tokens = get_max_input_tokens(
                    model_name=llm.config.model_name,
                    model_provider=llm.config.model_provider,
                )
                max_history_tokens = int(input_tokens * thread_context_percent)

                remaining_tokens = input_tokens - max_history_tokens

                query_text = new_message_request.messages[0].message
                if persona:
                    max_document_tokens = compute_max_document_tokens_for_persona(
                        persona=persona,
                        actual_user_input=query_text,
                        max_llm_token_override=remaining_tokens,
                    )
                else:
                    max_document_tokens = (
                        remaining_tokens
                        - 512  # Needs to be more than any of the QA prompts
                        - check_number_of_tokens(query_text)
                    )

            if DISABLE_GENERATIVE_AI:
                return None

            # This also handles creating the query event in postgres
            answer = get_search_answer(
                query_req=new_message_request,
                user=None,
                max_document_tokens=max_document_tokens,
                max_history_tokens=max_history_tokens,
                db_session=db_session,
                answer_generation_timeout=answer_generation_timeout,
                enable_reflexion=reflexion,
                bypass_acl=bypass_acl,
                use_citations=use_citations,
                danswerbot_flow=True,
            )
            if not answer.error_msg:
                return answer
            else:
                raise RuntimeError(answer.error_msg)

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
            slack_bot_config.enable_auto_filters
            if slack_bot_config is not None
            else False
        )
        retrieval_details = RetrievalDetails(
            run_search=OptionalSearchSetting.ALWAYS,
            real_time=False,
            filters=filters,
            enable_auto_detect_filters=auto_detect_filters,
        )

        # This includes throwing out answer via reflexion
        answer = _get_answer(
            DirectQARequest(
                messages=messages,
                prompt_id=prompt.id if prompt else None,
                persona_id=persona.id if persona is not None else 0,
                retrieval_options=retrieval_details,
                chain_of_thought=not disable_cot,
                skip_rerank=not ENABLE_RERANKING_ASYNC_FLOW,
            )
        )
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
                text="Hello! Danswer has some results for you!",
                blocks=[
                    SectionBlock(
                        text="Danswer is down for maintenance.\nWe're working hard on recharging the AI!"
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
        logger.info(
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
            f"Unable to answer question: '{answer.rephrase}' - no documents found"
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
        logger.info(
            "Unable to find answer - not responding since the "
            "`DANSWER_BOT_DISABLE_DOCS_ONLY_ANSWER` env variable is set"
        )
        return True

    only_respond_with_citations_or_quotes = (
        channel_conf
        and "well_answered_postfilter" in channel_conf.get("answer_filters", [])
    )
    has_citations_or_quotes = bool(answer.citations or answer.quotes)
    if (
        only_respond_with_citations_or_quotes
        and not has_citations_or_quotes
        and not message_info.bypass_filters
    ):
        logger.error(
            f"Unable to find citations or quotes to answer: '{answer.rephrase}' - not answering!"
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

    # If called with the DanswerBot slash command, the question is lost so we have to reshow it
    restate_question_block = get_restate_blocks(messages[-1].message, is_bot_msg)

    answer_blocks = build_qa_response_blocks(
        message_id=answer.chat_message_id,
        answer=answer.answer,
        quotes=answer.quotes.quotes if answer.quotes else None,
        source_filters=retrieval_info.applied_source_filters,
        time_cutoff=retrieval_info.applied_time_cutoff,
        favor_recent=retrieval_info.recency_bias_multiplier > 1,
        # currently Personas don't support quotes
        # if citations are enabled, also don't use quotes
        skip_quotes=persona is not None or use_citations,
        process_message_for_citations=use_citations,
        feedback_reminder_id=feedback_reminder_id,
    )

    # Get the chunks fed to the LLM only, then fill with other docs
    llm_doc_inds = answer.llm_chunks_indices or []
    llm_docs = [top_docs[i] for i in llm_doc_inds]
    remaining_docs = [
        doc for idx, doc in enumerate(top_docs) if idx not in llm_doc_inds
    ]
    priority_ordered_docs = llm_docs + remaining_docs

    document_blocks = []
    citations_block = []
    # if citations are enabled, only show cited documents
    if use_citations:
        citations = answer.citations or []
        cited_docs = []
        for citation in citations:
            matching_doc = next(
                (d for d in top_docs if d.document_id == citation.document_id),
                None,
            )
            if matching_doc:
                cited_docs.append((citation.citation_num, matching_doc))

        cited_docs.sort()
        citations_block = build_sources_blocks(cited_documents=cited_docs)
    elif priority_ordered_docs:
        document_blocks = build_documents_blocks(
            documents=priority_ordered_docs,
            message_id=answer.chat_message_id,
        )
        document_blocks = [DividerBlock()] + document_blocks

    all_blocks = (
        restate_question_block + answer_blocks + citations_block + document_blocks
    )

    if channel_conf and channel_conf.get("follow_up_tags") is not None:
        all_blocks.append(build_follow_up_block(message_id=answer.chat_message_id))

    try:
        respond_in_thread(
            client=client,
            channel=channel,
            receiver_ids=receiver_ids,
            text="Hello! Danswer has some results for you!",
            blocks=all_blocks,
            thread_ts=message_ts_to_respond_to,
            # don't unfurl, since otherwise we will have 5+ previews which makes the message very long
            unfurl=False,
        )

        # For DM (ephemeral message), we need to create a thread via a normal message so the user can see
        # the ephemeral message. This also will give the user a notification which ephemeral message does not.
        if receiver_ids:
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
