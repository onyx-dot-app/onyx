import re
from datetime import datetime
from datetime import timedelta
from typing import Any

from langchain_core.messages import HumanMessage
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy.orm import Session

from onyx.configs.app_configs import ENABLE_CONTEXTUAL_RAG
from onyx.configs.app_configs import MAX_SLACK_QUERY_EXPANSIONS
from onyx.configs.chat_configs import DOC_TIME_DECAY
from onyx.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from onyx.connectors.models import IndexingDocument
from onyx.connectors.models import TextSection
from onyx.context.search.federated.models import SlackMessage
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import SearchQuery
from onyx.db.document import DocumentSource
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.document_index_utils import (
    get_multipass_config,
)
from onyx.indexing.chunker import Chunker
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.models import DocAwareChunk
from onyx.llm.factory import get_default_llms
from onyx.llm.interfaces import LLM
from onyx.llm.utils import message_to_string
from onyx.onyxbot.slack.models import ChannelType
from onyx.onyxbot.slack.models import SlackContext
from onyx.prompts.federated_search import SLACK_QUERY_EXPANSION_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.timing import log_function_time

logger = setup_logger()

HIGHLIGHT_START_CHAR = "\ue000"
HIGHLIGHT_END_CHAR = "\ue001"


def _should_skip_channel(
    channel_id: str,
    allowed_private_channel: str | None,
    bot_token: str | None,
    access_token: str,
    include_dm: bool,
) -> bool:
    """
    Determine if a channel should be skipped if in bot context. When an allowed_private_channel is passed in,
    all other private channels are filtered out except that specific one.
    """
    if bot_token and not include_dm:
        try:
            # Use bot token if available (has full permissions), otherwise fall back to user token
            token_to_use = bot_token or access_token
            channel_client = WebClient(token=token_to_use)
            channel_info = channel_client.conversations_info(channel=channel_id)

            if isinstance(channel_info.data, dict) and not _is_public_channel(
                channel_info.data
            ):
                # This is a private channel - filter it out
                if channel_id != allowed_private_channel:
                    logger.debug(
                        f"Skipping message from private channel {channel_id} "
                        f"(not the allowed private channel: {allowed_private_channel})"
                    )
                    return True
        except Exception as e:
            logger.warning(
                f"Could not determine channel type for {channel_id}, filtering out: {e}"
            )
            return True
    return False


def build_slack_queries(query: SearchQuery, llm: LLM) -> list[str]:
    # get time filter
    time_filter = ""
    time_cutoff = query.filters.time_cutoff
    if time_cutoff is not None:
        # slack after: is exclusive, so we need to subtract one day
        time_cutoff = time_cutoff - timedelta(days=1)
        time_filter = f" after:{time_cutoff.strftime('%Y-%m-%d')}"

    # use llm to generate slack queries (use original query to use same keywords as the user)
    prompt = SLACK_QUERY_EXPANSION_PROMPT.format(query=query.original_query)
    try:
        msg = HumanMessage(content=prompt)
        response = llm.invoke([msg])
        rephrased_queries = message_to_string(response).split("\n")
    except Exception as e:
        logger.error(f"Error expanding query: {e}")
        rephrased_queries = [query.query]

    return [
        rephrased_query.strip() + time_filter
        for rephrased_query in rephrased_queries[:MAX_SLACK_QUERY_EXPANSIONS]
    ]


def _is_public_channel(channel_info: dict[str, Any]) -> bool:
    """Check if a channel is public based on its info"""
    # The channel_info structure has a nested 'channel' object
    channel = channel_info.get("channel", {})

    is_channel = channel.get("is_channel", False)
    is_private = channel.get("is_private", False)
    is_group = channel.get("is_group", False)
    is_mpim = channel.get("is_mpim", False)
    is_im = channel.get("is_im", False)

    # A public channel is: a channel that is NOT private, NOT a group, NOT mpim, NOT im
    is_public = (
        is_channel and not is_private and not is_group and not is_mpim and not is_im
    )

    return is_public


def query_slack(
    query_string: str,
    original_query: SearchQuery,
    access_token: str,
    limit: int | None = None,
    allowed_private_channel: str | None = None,
    bot_token: str | None = None,
    include_dm: bool = False,
) -> list[SlackMessage]:
    # query slack
    slack_client = WebClient(token=access_token)
    try:
        response = slack_client.search_messages(
            query=query_string, count=limit, highlight=True
        )
        response.validate()
        messages: dict[str, Any] = response.get("messages", {})
        matches: list[dict[str, Any]] = messages.get("matches", [])
        logger.info(f"Successfully used search_messages, found {len(matches)} messages")
    except SlackApiError as slack_error:
        logger.error(f"Slack API error in search_messages: {slack_error}")
        logger.error(
            f"Slack API error details: status={slack_error.response.status_code}, "
            f"error={slack_error.response.get('error')}"
        )
        if "not_allowed_token_type" in str(slack_error):
            # Log token type prefix
            token_prefix = access_token[:4] if len(access_token) >= 4 else "unknown"
            logger.error(f"TOKEN TYPE ERROR: access_token type: {token_prefix}...")
        return []

    # convert matches to slack messages
    slack_messages: list[SlackMessage] = []
    filtered_count = 0
    for match in matches:
        text: str | None = match.get("text")
        permalink: str | None = match.get("permalink")
        message_id: str | None = match.get("ts")
        channel_id: str | None = match.get("channel", {}).get("id")
        channel_name: str | None = match.get("channel", {}).get("name")
        username: str | None = match.get("username")
        if not username:
            # Fallback: try to get from user field if username is missing
            user_info = match.get("user", "")
            if isinstance(user_info, str) and user_info:
                username = user_info  # Use user ID as fallback
            else:
                username = "unknown_user"
        score: float = match.get("score", 0.0)
        if (  # can't use any() because of type checking :(
            not text
            or not permalink
            or not message_id
            or not channel_id
            or not channel_name
            or not username
        ):
            continue

        # Apply channel filtering if needed
        if _should_skip_channel(
            channel_id, allowed_private_channel, bot_token, access_token, include_dm
        ):
            filtered_count += 1
            continue

        # generate thread id and document id
        thread_id = (
            permalink.split("?thread_ts=", 1)[1] if "?thread_ts=" in permalink else None
        )
        document_id = f"{channel_id}_{message_id}"

        # compute recency bias (parallels vespa calculation) and metadata
        decay_factor = DOC_TIME_DECAY * original_query.recency_bias_multiplier
        doc_time = datetime.fromtimestamp(float(message_id))
        doc_age_years = (datetime.now() - doc_time).total_seconds() / (
            365 * 24 * 60 * 60
        )
        recency_bias = max(1 / (1 + decay_factor * doc_age_years), 0.75)
        metadata: dict[str, str | list[str]] = {
            "channel": channel_name,
            "time": doc_time.isoformat(),
        }

        # extract out the highlighted texts
        highlighted_texts = set(
            re.findall(
                rf"{re.escape(HIGHLIGHT_START_CHAR)}(.*?){re.escape(HIGHLIGHT_END_CHAR)}",
                text,
            )
        )
        cleaned_text = text.replace(HIGHLIGHT_START_CHAR, "").replace(
            HIGHLIGHT_END_CHAR, ""
        )

        # get the semantic identifier
        snippet = (
            cleaned_text[:50].rstrip() + "..." if len(cleaned_text) > 50 else text
        ).replace("\n", " ")
        doc_sem_id = f"{username} in #{channel_name}: {snippet}"

        slack_messages.append(
            SlackMessage(
                document_id=document_id,
                channel_id=channel_id,
                message_id=message_id,
                thread_id=thread_id,
                link=permalink,
                metadata=metadata,
                timestamp=doc_time,
                recency_bias=recency_bias,
                semantic_identifier=doc_sem_id,
                text=f"{username}: {cleaned_text}",
                highlighted_texts=highlighted_texts,
                slack_score=score,
            )
        )

    if filtered_count > 0:
        logger.info(
            f"Channel filtering applied: {filtered_count} messages filtered out, {len(slack_messages)} messages kept"
        )

    return slack_messages


def merge_slack_messages(
    slack_messages: list[list[SlackMessage]],
) -> tuple[list[SlackMessage], dict[str, SlackMessage]]:
    merged_messages: list[SlackMessage] = []
    docid_to_message: dict[str, SlackMessage] = {}

    for messages in slack_messages:
        for message in messages:
            if message.document_id in docid_to_message:
                # update the score and highlighted texts, rest should be identical
                docid_to_message[message.document_id].slack_score = max(
                    docid_to_message[message.document_id].slack_score,
                    message.slack_score,
                )
                docid_to_message[message.document_id].highlighted_texts.update(
                    message.highlighted_texts
                )
                continue

            # add the message to the list
            docid_to_message[message.document_id] = message
            merged_messages.append(message)

    # re-sort by score
    merged_messages.sort(key=lambda x: x.slack_score, reverse=True)

    return merged_messages, docid_to_message


def get_contextualized_thread_text(message: SlackMessage, access_token: str) -> str:
    """
    Retrieves the initial thread message as well as the text following the message
    and combines them into a single string. If the slack query fails, returns the
    original message text.

    The idea is that the message (the one that actually matched the search), the
    initial thread message, and the replies to the message are important in answering
    the user's query.
    """
    channel_id = message.channel_id
    thread_id = message.thread_id
    message_id = message.message_id

    # if it's not a thread, return the message text
    if thread_id is None:
        return message.text

    # get the thread messages
    slack_client = WebClient(token=access_token)
    try:
        response = slack_client.conversations_replies(
            channel=channel_id,
            ts=thread_id,
        )
        response.validate()
        messages: list[dict[str, Any]] = response.get("messages", [])
    except SlackApiError as e:
        logger.error(f"Slack API error in get_contextualized_thread_text: {e}")
        return message.text

    # make sure we didn't get an empty response or a single message (not a thread)
    if len(messages) <= 1:
        return message.text

    # add the initial thread message
    msg_text = messages[0].get("text", "")
    msg_sender = messages[0].get("user", "")
    thread_text = f"<@{msg_sender}>: {msg_text}"

    # add the message (unless it's the initial message)
    thread_text += "\n\nReplies:"
    if thread_id == message_id:
        message_id_idx = 0
    else:
        message_id_idx = next(
            (i for i, msg in enumerate(messages) if msg.get("ts") == message_id), 0
        )
        if not message_id_idx:
            return thread_text

        # add the message
        thread_text += "\n..." if message_id_idx > 1 else ""
        msg_text = messages[message_id_idx].get("text", "")
        msg_sender = messages[message_id_idx].get("user", "")
        thread_text += f"\n<@{msg_sender}>: {msg_text}"

    # add the following replies to the thread text
    len_replies = 0
    for msg in messages[message_id_idx + 1 :]:
        msg_text = msg.get("text", "")
        msg_sender = msg.get("user", "")
        reply = f"\n\n<@{msg_sender}>: {msg_text}"
        thread_text += reply

        # stop if len_replies exceeds chunk_size * 4 chars as the rest likely won't fit
        len_replies += len(reply)
        if len_replies >= DOC_EMBEDDING_CONTEXT_SIZE * 4:
            thread_text += "\n..."
            break

    # replace user ids with names in the thread text
    userids: set[str] = set(re.findall(r"<@([A-Z0-9]+)>", thread_text))
    for userid in userids:
        try:
            response = slack_client.users_profile_get(user=userid)
            response.validate()
            profile: dict[str, Any] = response.get("profile", {})
            name: str | None = profile.get("real_name") or profile.get("email")
        except SlackApiError as e:
            logger.error(f"Slack API error in get_contextualized_thread_text: {e}")
            continue
        if not name:
            continue
        thread_text = thread_text.replace(f"<@{userid}>", name)

    return thread_text


def convert_slack_score(slack_score: float) -> float:
    """
    Convert slack score to a score between 0 and 1.
    Will affect UI ordering and LLM ordering, but not the pruning.
    I.e., should have very little effect on the search/answer quality.
    """
    return max(0.0, min(1.0, slack_score / 90_000))


@log_function_time(print_only=True)
def slack_retrieval(
    query: SearchQuery,
    access_token: str,
    db_session: Session,
    limit: int | None = None,
    slack_event_context: SlackContext | None = None,
    bot_token: str | None = None,  # Add bot token parameter
) -> list[InferenceChunk]:
    # query slack
    _, fast_llm = get_default_llms()
    query_strings = build_slack_queries(query, fast_llm)

    include_dm = False
    allowed_private_channel = None

    if slack_event_context:
        channel_type = slack_event_context.channel_type
        if channel_type == ChannelType.IM:  # DM with user
            include_dm = True
        if channel_type == ChannelType.PRIVATE_CHANNEL:
            allowed_private_channel = slack_event_context.channel_id
            logger.info(
                f"Private channel context: will only allow messages from {allowed_private_channel} + public channels"
            )

    results = run_functions_tuples_in_parallel(
        [
            (
                query_slack,
                (
                    query_string,
                    query,
                    access_token,
                    limit,
                    allowed_private_channel,
                    bot_token,
                    include_dm,
                ),
            )
            for query_string in query_strings
        ]
    )
    slack_messages, docid_to_message = merge_slack_messages(results)
    slack_messages = slack_messages[: limit or len(slack_messages)]
    if not slack_messages:
        return []

    thread_texts: list[str] = run_functions_tuples_in_parallel(
        [
            (get_contextualized_thread_text, (slack_message, access_token))
            for slack_message in slack_messages
        ]
    )
    for slack_message, thread_text in zip(slack_messages, thread_texts):
        slack_message.text = thread_text

    # get the highlighted texts from shortest to longest
    highlighted_texts: set[str] = set()
    for slack_message in slack_messages:
        highlighted_texts.update(slack_message.highlighted_texts)
    sorted_highlighted_texts = sorted(highlighted_texts, key=len)

    # convert slack messages to index documents
    index_docs: list[IndexingDocument] = []
    for slack_message in slack_messages:
        section: TextSection = TextSection(
            text=slack_message.text, link=slack_message.link
        )
        index_docs.append(
            IndexingDocument(
                id=slack_message.document_id,
                sections=[section],
                processed_sections=[section],
                source=DocumentSource.SLACK,
                title=slack_message.semantic_identifier,
                semantic_identifier=slack_message.semantic_identifier,
                metadata=slack_message.metadata,
                doc_updated_at=slack_message.timestamp,
            )
        )

    # chunk index docs into doc aware chunks
    # a single index doc can get split into multiple chunks
    search_settings = get_current_search_settings(db_session)
    embedder = DefaultIndexingEmbedder.from_db_search_settings(
        search_settings=search_settings
    )
    multipass_config = get_multipass_config(search_settings)
    enable_contextual_rag = (
        search_settings.enable_contextual_rag or ENABLE_CONTEXTUAL_RAG
    )
    chunker = Chunker(
        tokenizer=embedder.embedding_model.tokenizer,
        enable_multipass=multipass_config.multipass_indexing,
        enable_large_chunks=multipass_config.enable_large_chunks,
        enable_contextual_rag=enable_contextual_rag,
    )
    chunks = chunker.chunk(index_docs)

    # prune chunks without any highlighted texts
    relevant_chunks: list[DocAwareChunk] = []
    chunkid_to_match_highlight: dict[str, str] = {}
    for chunk in chunks:
        match_highlight = chunk.content
        for highlight in sorted_highlighted_texts:  # faster than re sub
            match_highlight = match_highlight.replace(
                highlight, f"<hi>{highlight}</hi>"
            )

        # if nothing got replaced, the chunk is irrelevant
        if len(match_highlight) == len(chunk.content):
            continue

        chunk_id = f"{chunk.source_document.id}__{chunk.chunk_id}"
        relevant_chunks.append(chunk)
        chunkid_to_match_highlight[chunk_id] = match_highlight
        if limit and len(relevant_chunks) >= limit:
            break

    # convert to inference chunks
    top_chunks: list[InferenceChunk] = []
    for chunk in relevant_chunks:
        document_id = chunk.source_document.id
        chunk_id = f"{document_id}__{chunk.chunk_id}"

        top_chunks.append(
            InferenceChunk(
                chunk_id=chunk.chunk_id,
                blurb=chunk.blurb,
                content=chunk.content,
                source_links=chunk.source_links,
                image_file_id=chunk.image_file_id,
                section_continuation=chunk.section_continuation,
                semantic_identifier=docid_to_message[document_id].semantic_identifier,
                document_id=document_id,
                source_type=DocumentSource.SLACK,
                title=chunk.title_prefix,
                boost=0,
                recency_bias=docid_to_message[document_id].recency_bias,
                score=convert_slack_score(docid_to_message[document_id].slack_score),
                hidden=False,
                is_relevant=None,
                relevance_explanation="",
                metadata=docid_to_message[document_id].metadata,
                match_highlights=[chunkid_to_match_highlight[chunk_id]],
                doc_summary="",
                chunk_context="",
                updated_at=docid_to_message[document_id].timestamp,
                is_federated=True,
            )
        )

    return top_chunks
