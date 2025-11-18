import json
import re
import time
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy.orm import Session

from onyx.configs.app_configs import ENABLE_CONTEXTUAL_RAG
from onyx.configs.chat_configs import DOC_TIME_DECAY
from onyx.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from onyx.connectors.models import IndexingDocument
from onyx.connectors.models import TextSection
from onyx.context.search.federated.models import SlackMessage
from onyx.context.search.federated.slack_search_utils import ALL_CHANNEL_TYPES
from onyx.context.search.federated.slack_search_utils import build_channel_query_filter
from onyx.context.search.federated.slack_search_utils import build_slack_queries
from onyx.context.search.federated.slack_search_utils import ChannelTypeString
from onyx.context.search.federated.slack_search_utils import get_channel_type
from onyx.context.search.federated.slack_search_utils import (
    get_channel_type_for_missing_scope,
)
from onyx.context.search.federated.slack_search_utils import is_recency_query
from onyx.context.search.federated.slack_search_utils import should_include_message
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import SearchQuery
from onyx.db.document import DocumentSource
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.document_index_utils import (
    get_multipass_config,
)
from onyx.federated_connectors.slack.models import SlackEntities
from onyx.indexing.chunker import Chunker
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.models import DocAwareChunk
from onyx.llm.factory import get_default_llms
from onyx.onyxbot.slack.models import ChannelType
from onyx.onyxbot.slack.models import SlackContext
from onyx.redis.redis_pool import get_redis_client
from onyx.server.federated.models import FederatedConnectorDetail
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.timing import log_function_time

logger = setup_logger()

HIGHLIGHT_START_CHAR = "\ue000"
HIGHLIGHT_END_CHAR = "\ue001"

CHANNEL_METADATA_CACHE_TTL = 60 * 60 * 24  # 24 hours
SLACK_THREAD_CONTEXT_WINDOW = 3  # Number of messages before matched message to include
CHANNEL_METADATA_MAX_RETRIES = 3  # Maximum retry attempts for channel metadata fetching
CHANNEL_METADATA_RETRY_DELAY = 1  # Initial retry delay in seconds (exponential backoff)


def fetch_and_cache_channel_metadata(
    access_token: str, team_id: str, include_private: bool = True
) -> dict[str, dict[str, Any]]:
    """
    Fetch ALL channel metadata in one API call and cache it.

    Returns a dict mapping channel_id -> metadata including name, type, etc.
    This replaces multiple conversations.info calls with a single conversations.list.

    Note: We ALWAYS fetch all channel types (including private) and cache them together.
    This ensures a single cache entry per team, avoiding duplicate API calls.
    """
    # Use tenant-specific Redis client
    redis_client = get_redis_client()
    # (tenant_id prefix is added automatically by TenantRedis)
    cache_key = f"slack_federated_search:{team_id}:channels:metadata"

    try:
        cached = redis_client.get(cache_key)
        if cached:
            logger.info(f"Channel metadata cache HIT for team {team_id}")
            cached_str: str = (
                cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)
            )
            cached_data: dict[str, dict[str, Any]] = json.loads(cached_str)
            logger.info(f"Loaded {len(cached_data)} channels from cache")
            if not include_private:
                filtered = {
                    k: v
                    for k, v in cached_data.items()
                    if v.get("type") != "private_channel"
                }
                logger.info(f"Filtered to {len(filtered)} channels (exclude private)")
                return filtered
            return cached_data
    except Exception as e:
        logger.warning(f"Error reading from channel metadata cache: {e}")

    # Cache miss - fetch from Slack API with retry logic
    logger.info(f"Channel metadata cache MISS for team {team_id} - fetching from API")
    slack_client = WebClient(token=access_token)
    channel_metadata: dict[str, dict[str, Any]] = {}

    # Retry logic with exponential backoff
    last_exception = None
    available_channel_types = ALL_CHANNEL_TYPES.copy()

    for attempt in range(CHANNEL_METADATA_MAX_RETRIES):
        try:
            # Use available channel types (may be reduced if scopes are missing)
            channel_types = ",".join(available_channel_types)

            # Fetch all channels in one call
            cursor = None
            channel_count = 0
            while True:
                response = slack_client.conversations_list(
                    types=channel_types,
                    exclude_archived=True,
                    limit=1000,
                    cursor=cursor,
                )
                response.validate()

                # Cast response.data to dict for type checking
                response_data: dict[str, Any] = response.data  # type: ignore
                for ch in response_data.get("channels", []):
                    channel_id = ch.get("id")
                    if not channel_id:
                        continue

                    # Determine channel type
                    channel_type_enum = get_channel_type(channel_info=ch)
                    channel_type = channel_type_enum.value

                    channel_metadata[channel_id] = {
                        "name": ch.get("name", ""),
                        "type": channel_type,
                        "is_private": ch.get("is_private", False),
                        "is_member": ch.get("is_member", False),
                    }
                    channel_count += 1

                cursor = response_data.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break

            logger.info(f"Fetched {channel_count} channels for team {team_id}")

            # Cache the results
            try:
                redis_client.set(
                    cache_key,
                    json.dumps(channel_metadata),
                    ex=CHANNEL_METADATA_CACHE_TTL,
                )
                logger.info(
                    f"Cached {channel_count} channels for team {team_id} (TTL: {CHANNEL_METADATA_CACHE_TTL}s, key: {cache_key})"
                )
            except Exception as e:
                logger.warning(f"Error caching channel metadata: {e}")

            return channel_metadata

        except SlackApiError as e:
            last_exception = e
            error_response = e.response.get("error", "") if e.response else ""

            # Check if this is a missing_scope error
            if error_response == "missing_scope" and e.response:
                needed_scope = e.response.get("needed", "")

                # Get the channel type that requires this scope
                missing_channel_type = get_channel_type_for_missing_scope(needed_scope)

                if (
                    missing_channel_type
                    and missing_channel_type in available_channel_types
                ):
                    # Remove the problematic channel type and retry
                    available_channel_types.remove(missing_channel_type)
                    logger.warning(
                        f"Missing scope '{needed_scope}' for channel type '{missing_channel_type}'. "
                        f"Continuing with reduced channel types: {available_channel_types}"
                    )
                    # Don't count this as a retry attempt, just try again with fewer types
                    continue
                else:
                    logger.error(
                        f"Missing scope '{needed_scope}' but could not map to channel type or already removed. "
                        f"Response: {e.response}"
                    )

            # For other errors, use retry logic
            if attempt < CHANNEL_METADATA_MAX_RETRIES - 1:
                retry_delay = CHANNEL_METADATA_RETRY_DELAY * (2**attempt)
                logger.warning(
                    f"Failed to fetch channel metadata (attempt {attempt + 1}/{CHANNEL_METADATA_MAX_RETRIES}): {e}. "
                    f"Retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)
            else:
                logger.error(
                    f"Failed to fetch channel metadata after {CHANNEL_METADATA_MAX_RETRIES} attempts: {e}"
                )

    # If we have some channel metadata despite errors, return it with a warning
    if channel_metadata:
        logger.warning(
            f"Returning partial channel metadata ({len(channel_metadata)} channels) despite errors. "
            f"Last error: {last_exception}"
        )
        return channel_metadata

    # If we exhausted all retries and have no data, raise the last exception
    if last_exception:
        raise SlackApiError(
            f"Channel metadata fetching failed after {CHANNEL_METADATA_MAX_RETRIES} attempts",
            last_exception.response,
        )

    return {}


def get_available_channels(
    access_token: str, team_id: str, include_private: bool = False
) -> list[str]:
    """Fetch list of available channel names using cached metadata."""
    metadata = fetch_and_cache_channel_metadata(access_token, team_id, include_private)
    return [meta["name"] for meta in metadata.values() if meta["name"]]


def _extract_channel_data_from_entities(
    entities: dict[str, Any] | None,
    channel_metadata_dict: dict[str, dict[str, Any]] | None,
) -> list[str] | None:
    """Extract available channels list from metadata based on entity configuration.

    Args:
        entities: Entity filter configuration dict
        channel_metadata_dict: Pre-fetched channel metadata dictionary

    Returns:
        List of available channel names, or None if not needed
    """
    if not entities or not channel_metadata_dict:
        return None

    try:
        parsed_entities = SlackEntities(**entities)
        # Only extract if we have exclusions or channel filters
        if parsed_entities.exclude_channels or parsed_entities.channels:
            # Extract channel names from metadata dict
            return [
                meta["name"]
                for meta in channel_metadata_dict.values()
                if meta["name"]
                and (
                    parsed_entities.include_private_channels
                    or meta.get("type") != ChannelTypeString.PRIVATE_CHANNEL.value
                )
            ]
    except ValidationError:
        logger.debug("Failed to parse entities for channel data extraction")

    return None


def _should_skip_channel(
    channel_id: str,
    allowed_private_channel: str | None,
    bot_token: str | None,
    access_token: str,
    include_dm: bool,
) -> bool:
    """Bot context filtering: skip private channels unless explicitly allowed."""
    if bot_token and not include_dm:
        try:
            token_to_use = bot_token or access_token
            channel_client = WebClient(token=token_to_use)
            channel_info = channel_client.conversations_info(channel=channel_id)

            if isinstance(channel_info.data, dict):
                channel_data = channel_info.data.get("channel", {})
                channel_type = get_channel_type(channel_info=channel_data)
                is_private_or_dm = channel_type in [
                    ChannelType.PRIVATE_CHANNEL,
                    ChannelType.IM,
                    ChannelType.MPIM,
                ]

                if is_private_or_dm and channel_id != allowed_private_channel:
                    return True
        except Exception as e:
            logger.warning(
                f"Could not determine channel type for {channel_id}, filtering out: {e}"
            )
            return True
    return False


def query_slack(
    query_string: str,
    original_query: SearchQuery,
    access_token: str,
    limit: int | None = None,
    allowed_private_channel: str | None = None,
    bot_token: str | None = None,
    include_dm: bool = False,
    entities: dict[str, Any] | None = None,
    available_channels: list[str] | None = None,
) -> list[SlackMessage]:

    # Check if query has channel override (user specified channels in query)
    has_channel_override = query_string.startswith("__CHANNEL_OVERRIDE__")

    if has_channel_override:
        # Remove the marker and use the query as-is (already has channel filters)
        final_query = query_string.replace("__CHANNEL_OVERRIDE__", "").strip()
    else:
        # Normal flow: build channel filters from entity config
        channel_filter = ""
        if entities:
            channel_filter = build_channel_query_filter(entities, available_channels)

        final_query = query_string
        if channel_filter:
            # Add channel filter to query
            final_query = f"{query_string} {channel_filter}"

    logger.info(f"Final query to slack: {final_query}")

    # Detect if query asks for most recent results
    sort_by_time = is_recency_query(original_query.query)

    slack_client = WebClient(token=access_token)
    try:
        search_params: dict[str, Any] = {
            "query": final_query,
            "count": limit,
            "highlight": True,
        }

        # Sort by timestamp for recency-focused queries, otherwise by relevance
        if sort_by_time:
            search_params["sort"] = "timestamp"
            search_params["sort_dir"] = "desc"

        response = slack_client.search_messages(**search_params)
        response.validate()

        messages: dict[str, Any] = response.get("messages", {})
        matches: list[dict[str, Any]] = messages.get("matches", [])

        logger.info(f"Slack search found {len(matches)} messages")
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

        # Include a few messages BEFORE the matched message for context
        # This helps understand what the matched message is responding to
        start_idx = max(
            1, message_id_idx - SLACK_THREAD_CONTEXT_WINDOW
        )  # Start after thread starter

        # Add ellipsis if we're skipping messages between thread starter and context window
        if start_idx > 1:
            thread_text += "\n..."

        # Add context messages before the matched message
        for i in range(start_idx, message_id_idx):
            msg_text = messages[i].get("text", "")
            msg_sender = messages[i].get("user", "")
            thread_text += f"\n\n<@{msg_sender}>: {msg_text}"

        # Add the matched message itself
        msg_text = messages[message_id_idx].get("text", "")
        msg_sender = messages[message_id_idx].get("user", "")
        thread_text += f"\n\n<@{msg_sender}>: {msg_text}"

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
            # user_not_found is common for deleted users, bots, etc. - not critical
            if "user_not_found" in str(e):
                logger.debug(
                    f"User {userid} not found in Slack workspace (likely deleted/deactivated)"
                )
            else:
                logger.warning(f"Could not fetch profile for user {userid}: {e}")
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
    connector: FederatedConnectorDetail | None = None,
    entities: dict[str, Any] | None = None,
    limit: int | None = None,
    slack_event_context: SlackContext | None = None,
    bot_token: str | None = None,  # Add bot token parameter
    team_id: str | None = None,
) -> list[InferenceChunk]:
    """
    Main entry point for Slack federated search with entity filtering.

    Applies entity filtering including:
    - Channel selection and exclusion
    - Date range extraction and enforcement
    - DM/private channel filtering
    - Multi-layer caching

    Args:
        query: Search query object
        access_token: User OAuth access token
        db_session: Database session
        connector: Federated connector detail (unused, kept for backwards compat)
        entities: Connector-level config (entity filtering configuration)
        limit: Maximum number of results
        slack_event_context: Context when called from Slack bot
        bot_token: Bot token for enhanced permissions
        team_id: Slack team/workspace ID

    Returns:
        List of InferenceChunk objects
    """
    # Use connector-level config
    entities = entities or {}

    if not entities:
        logger.info("No entity configuration found, using defaults")
    else:
        logger.info(f"Using entity configuration: {entities}")

    # Extract limit from entity config if not explicitly provided
    query_limit = limit
    if entities:
        try:
            parsed_entities = SlackEntities(**entities)
            if limit is None:
                query_limit = parsed_entities.max_messages_per_query
                logger.info(f"Using max_messages_per_query from config: {query_limit}")
        except Exception as e:
            logger.warning(f"Error parsing entities for limit: {e}")
            if limit is None:
                query_limit = 100  # Fallback default
    elif limit is None:
        query_limit = 100  # Default when no entities and no limit provided

    # Pre-fetch channel metadata from Redis cache and extract available channels
    # This avoids repeated Redis lookups during parallel search execution
    available_channels = None
    channel_metadata_dict = None
    if team_id:
        # Always fetch all channel types (include_private=True) to ensure single cache entry
        channel_metadata_dict = fetch_and_cache_channel_metadata(
            access_token, team_id, include_private=True
        )

        # Extract available channels list if needed for pattern matching
        available_channels = _extract_channel_data_from_entities(
            entities, channel_metadata_dict
        )

    # Query slack with entity filtering
    _, fast_llm = get_default_llms()
    query_strings = build_slack_queries(query, fast_llm, entities, available_channels)

    # Determine filtering based on entities OR context (bot)
    include_dm = False
    allowed_private_channel = None

    # Bot context overrides (if entities not specified)
    if slack_event_context and not entities:
        channel_type = slack_event_context.channel_type
        if channel_type == ChannelType.IM:  # DM with user
            include_dm = True
        if channel_type == ChannelType.PRIVATE_CHANNEL:
            allowed_private_channel = slack_event_context.channel_id
            logger.info(
                f"Private channel context: will only allow messages from {allowed_private_channel} + public channels"
            )

    # Build search tasks
    search_tasks = [
        (
            query_slack,
            (
                query_string,
                query,
                access_token,
                query_limit,
                allowed_private_channel,
                bot_token,
                include_dm,
                entities,
                available_channels,
            ),
        )
        for query_string in query_strings
    ]

    # If include_dm is True, add additional searches without channel filters
    # This allows searching DMs/group DMs while still searching the specified channels
    if entities and entities.get("include_dm"):
        # Create a minimal entities dict that won't add channel filters
        # This ensures we search ALL conversations (DMs, group DMs, private channels)
        # BUT we still want to exclude channels specified in exclude_channels
        dm_entities = {
            "include_dm": True,
            "include_private_channels": entities.get("include_private_channels", False),
            "default_search_days": entities.get("default_search_days", 30),
            "search_all_channels": True,
            "channels": None,
            "exclude_channels": entities.get(
                "exclude_channels"
            ),  # ALWAYS apply exclude_channels
        }

        for query_string in query_strings:
            search_tasks.append(
                (
                    query_slack,
                    (
                        query_string,
                        query,
                        access_token,
                        query_limit,
                        allowed_private_channel,
                        bot_token,
                        include_dm,
                        dm_entities,
                        available_channels,
                    ),
                )
            )

    # Execute searches in parallel
    results = run_functions_tuples_in_parallel(search_tasks)

    # Merge and post-filter results
    slack_messages, docid_to_message = merge_slack_messages(results)

    # Post-filter by channel type (DM, private channel, etc.)
    # NOTE: We must post-filter because Slack's search.messages API only supports
    # filtering by channel NAME (via in:#channel syntax), not by channel TYPE.
    # There's no way to specify "only public channels" or "exclude DMs" in the query.
    if entities and team_id:
        # Use pre-fetched channel metadata to avoid cache misses
        # Pass it directly instead of relying on Redis cache

        filtered_messages = []
        removed_count = 0
        for msg in slack_messages:
            # Pass pre-fetched metadata to avoid cache lookups
            channel_type = get_channel_type(
                channel_id=msg.channel_id,
                channel_metadata=channel_metadata_dict,
            )
            if should_include_message(channel_type, entities):
                filtered_messages.append(msg)
            else:
                removed_count += 1

        if removed_count > 0:
            logger.info(
                f"Post-filtering removed {removed_count} messages: "
                f"{len(slack_messages)} -> {len(filtered_messages)}"
            )
        slack_messages = filtered_messages

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

    # For queries without highlights (e.g., empty recency queries), we should keep all chunks
    has_highlights = len(sorted_highlighted_texts) > 0

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
    # BUT: for recency queries without keywords, keep all chunks
    relevant_chunks: list[DocAwareChunk] = []
    chunkid_to_match_highlight: dict[str, str] = {}

    if not has_highlights:
        # No highlighted terms - keep all chunks (recency query)
        for chunk in chunks:
            chunk_id = f"{chunk.source_document.id}__{chunk.chunk_id}"
            relevant_chunks.append(chunk)
            chunkid_to_match_highlight[chunk_id] = chunk.content  # No highlighting
            if limit and len(relevant_chunks) >= limit:
                break
    else:
        # Prune chunks that don't contain highlighted terms
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
