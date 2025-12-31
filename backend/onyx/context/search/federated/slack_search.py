import json
import re
import time
from datetime import datetime
from typing import Any
from typing import cast

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import ValidationError
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy.orm import Session

from onyx.configs.app_configs import ENABLE_CONTEXTUAL_RAG
from onyx.configs.app_configs import MAX_SLACK_THREAD_CONTEXT_MESSAGES
from onyx.configs.app_configs import SLACK_THREAD_CONTEXT_BATCH_SIZE
from onyx.configs.chat_configs import DOC_TIME_DECAY
from onyx.connectors.models import IndexingDocument
from onyx.connectors.models import TextSection
from onyx.context.search.federated.models import ChannelMetadata
from onyx.context.search.federated.models import SlackMessage
from onyx.context.search.federated.slack_search_utils import ALL_CHANNEL_TYPES
from onyx.context.search.federated.slack_search_utils import build_channel_query_filter
from onyx.context.search.federated.slack_search_utils import build_slack_queries
from onyx.context.search.federated.slack_search_utils import get_channel_type
from onyx.context.search.federated.slack_search_utils import (
    get_channel_type_for_missing_scope,
)
from onyx.context.search.federated.slack_search_utils import is_recency_query
from onyx.context.search.federated.slack_search_utils import should_include_message
from onyx.context.search.models import ChunkIndexRequest
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
from onyx.llm.factory import get_default_llm
from onyx.onyxbot.slack.models import ChannelType
from onyx.onyxbot.slack.models import SlackContext
from onyx.redis.redis_pool import get_redis_client
from onyx.server.federated.models import FederatedConnectorDetail
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.timing import log_function_time
from shared_configs.configs import DOC_EMBEDDING_CONTEXT_SIZE

logger = setup_logger()

HIGHLIGHT_START_CHAR = "\ue000"
HIGHLIGHT_END_CHAR = "\ue001"

CHANNEL_METADATA_CACHE_TTL = 60 * 60 * 24  # 24 hours
USER_PROFILE_CACHE_TTL = 60 * 60 * 24  # 24 hours
SLACK_THREAD_CONTEXT_WINDOW = 3  # Number of messages before matched message to include
CHANNEL_METADATA_MAX_RETRIES = 3  # Maximum retry attempts for channel metadata fetching
CHANNEL_METADATA_RETRY_DELAY = 1  # Initial retry delay in seconds (exponential backoff)


def fetch_and_cache_channel_metadata(
    access_token: str, team_id: str, include_private: bool = True
) -> dict[str, ChannelMetadata]:
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
            logger.debug(f"Channel metadata cache HIT for team {team_id}")
            cached_str: str = (
                cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)
            )
            cached_data = cast(dict[str, ChannelMetadata], json.loads(cached_str))
            logger.debug(f"Loaded {len(cached_data)} channels from cache")
            if not include_private:
                filtered: dict[str, ChannelMetadata] = {
                    k: v
                    for k, v in cached_data.items()
                    if v.get("type") != ChannelType.PRIVATE_CHANNEL.value
                }
                logger.debug(f"Filtered to {len(filtered)} channels (exclude private)")
                return filtered
            return cached_data
    except Exception as e:
        logger.warning(f"Error reading from channel metadata cache: {e}")

    # Cache miss - fetch from Slack API with retry logic
    logger.debug(f"Channel metadata cache MISS for team {team_id} - fetching from API")
    slack_client = WebClient(token=access_token)
    channel_metadata: dict[str, ChannelMetadata] = {}

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
                    channel_type = ChannelType(channel_type_enum.value)

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

            # Extract all needed fields from response upfront
            if e.response:
                error_response = e.response.get("error", "")
                needed_scope = e.response.get("needed", "")
            else:
                error_response = ""
                needed_scope = ""

            # Check if this is a missing_scope error
            if error_response == "missing_scope":

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
                    if available_channel_types:  # Only continue if we have types left
                        continue
                    # Otherwise fall through to retry logic
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


def get_cached_user_profile(
    access_token: str, team_id: str, user_id: str
) -> str | None:
    """
    Get a user's display name from cache or fetch from Slack API.

    Uses Redis caching to avoid repeated API calls and rate limiting.
    Returns the user's real_name or email, or None if not found.
    """
    redis_client = get_redis_client()
    cache_key = f"slack_federated_search:{team_id}:user:{user_id}"

    # Check cache first
    try:
        cached = redis_client.get(cache_key)
        if cached is not None:
            cached_str = (
                cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)
            )
            # Empty string means user was not found previously
            return cached_str if cached_str else None
    except Exception as e:
        logger.debug(f"Error reading user profile cache: {e}")

    # Cache miss - fetch from Slack API
    slack_client = WebClient(token=access_token)
    try:
        response = slack_client.users_profile_get(user=user_id)
        response.validate()
        profile: dict[str, Any] = response.get("profile", {})
        name: str | None = profile.get("real_name") or profile.get("email")

        # Cache the result (empty string for not found)
        try:
            redis_client.set(
                cache_key,
                name or "",
                ex=USER_PROFILE_CACHE_TTL,
            )
        except Exception as e:
            logger.debug(f"Error caching user profile: {e}")

        return name

    except SlackApiError as e:
        error_str = str(e)
        if "user_not_found" in error_str:
            logger.debug(
                f"User {user_id} not found in Slack workspace (likely deleted/deactivated)"
            )
        elif "ratelimited" in error_str:
            # Don't cache rate limit errors - we'll retry later
            logger.debug(f"Rate limited fetching user {user_id}, will retry later")
            return None
        else:
            logger.warning(f"Could not fetch profile for user {user_id}: {e}")

        # Cache negative result to avoid repeated lookups for missing users
        try:
            redis_client.set(cache_key, "", ex=USER_PROFILE_CACHE_TTL)
        except Exception:
            pass

        return None


def batch_get_user_profiles(
    access_token: str, team_id: str, user_ids: set[str]
) -> dict[str, str]:
    """
    Batch fetch user profiles with caching.

    Returns a dict mapping user_id -> display_name for users that were found.
    """
    result: dict[str, str] = {}

    for user_id in user_ids:
        name = get_cached_user_profile(access_token, team_id, user_id)
        if name:
            result[user_id] = name

    return result


def _extract_channel_data_from_entities(
    entities: dict[str, Any] | None,
    channel_metadata_dict: dict[str, ChannelMetadata] | None,
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
                    or meta.get("type") != ChannelType.PRIVATE_CHANNEL.value
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
    channel_metadata_dict: dict[str, ChannelMetadata] | None = None,
) -> bool:
    """Bot context filtering: skip private channels unless explicitly allowed.

    Uses pre-fetched channel metadata when available to avoid API calls.
    """
    if bot_token and not include_dm:
        try:
            # First try to use pre-fetched metadata from cache
            if channel_metadata_dict and channel_id in channel_metadata_dict:
                channel_meta = channel_metadata_dict[channel_id]
                channel_type_str = channel_meta.get("type", "")
                is_private_or_dm = channel_type_str in [
                    ChannelType.PRIVATE_CHANNEL.value,
                    ChannelType.IM.value,
                    ChannelType.MPIM.value,
                ]
                if is_private_or_dm and channel_id != allowed_private_channel:
                    return True
                return False

            # Fallback: API call only if not in cache (should be rare)
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


class SlackQueryResult(BaseModel):
    """Result from a single Slack query including stats."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    messages: list[SlackMessage]
    filtered_channels: list[str]  # Channels filtered out during this query


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
    channel_metadata_dict: dict[str, ChannelMetadata] | None = None,
) -> SlackQueryResult:

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
        return SlackQueryResult(messages=[], filtered_channels=[])

    # convert matches to slack messages
    slack_messages: list[SlackMessage] = []
    filtered_channels: list[str] = []
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
            channel_id,
            allowed_private_channel,
            bot_token,
            access_token,
            include_dm,
            channel_metadata_dict,
        ):
            filtered_channels.append(f"{channel_name}({channel_id})")
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

    return SlackQueryResult(
        messages=slack_messages, filtered_channels=filtered_channels
    )


def merge_slack_messages(
    query_results: list[SlackQueryResult],
) -> tuple[list[SlackMessage], dict[str, SlackMessage], set[str]]:
    """Merge messages from multiple query results, deduplicating by document_id.

    Returns:
        Tuple of (merged_messages, docid_to_message, all_filtered_channels)
    """
    merged_messages: list[SlackMessage] = []
    docid_to_message: dict[str, SlackMessage] = {}
    all_filtered_channels: set[str] = set()

    for result in query_results:
        # Collect filtered channels from all queries
        all_filtered_channels.update(result.filtered_channels)

        for message in result.messages:
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

    return merged_messages, docid_to_message, all_filtered_channels


class SlackRateLimitError(Exception):
    """Raised when Slack API returns a rate limit error (429)."""


class ThreadContextResult:
    """Result wrapper for thread context fetch that captures error type."""

    __slots__ = ("text", "is_rate_limited", "is_error")

    def __init__(
        self, text: str, is_rate_limited: bool = False, is_error: bool = False
    ):
        self.text = text
        self.is_rate_limited = is_rate_limited
        self.is_error = is_error

    @classmethod
    def success(cls, text: str) -> "ThreadContextResult":
        return cls(text)

    @classmethod
    def rate_limited(cls, original_text: str) -> "ThreadContextResult":
        return cls(original_text, is_rate_limited=True)

    @classmethod
    def error(cls, original_text: str) -> "ThreadContextResult":
        return cls(original_text, is_error=True)


def _fetch_thread_context(
    message: SlackMessage, access_token: str, team_id: str | None = None
) -> ThreadContextResult:
    """
    Fetch thread context for a message, returning a result object.

    Returns ThreadContextResult with:
    - success: enriched thread text
    - rate_limited: original text + flag indicating we should stop
    - error: original text for other failures (graceful degradation)
    """
    channel_id = message.channel_id
    thread_id = message.thread_id
    message_id = message.message_id

    # If not a thread, return original text as success
    if thread_id is None:
        return ThreadContextResult.success(message.text)

    slack_client = WebClient(token=access_token, timeout=30)
    try:
        response = slack_client.conversations_replies(
            channel=channel_id,
            ts=thread_id,
        )
        response.validate()
        messages: list[dict[str, Any]] = response.get("messages", [])
    except SlackApiError as e:
        # Check for rate limit error specifically
        if e.response and e.response.status_code == 429:
            logger.warning(
                f"Slack rate limit hit while fetching thread context for {channel_id}/{thread_id}"
            )
            return ThreadContextResult.rate_limited(message.text)
        # For other Slack errors, log and return original text
        logger.error(f"Slack API error in thread context fetch: {e}")
        return ThreadContextResult.error(message.text)
    except Exception as e:
        # Network errors, timeouts, etc - treat as recoverable error
        logger.error(f"Unexpected error in thread context fetch: {e}")
        return ThreadContextResult.error(message.text)

    # If empty response or single message (not a thread), return original text
    if len(messages) <= 1:
        return ThreadContextResult.success(message.text)

    # Build thread text from thread starter + context window around matched message
    thread_text = _build_thread_text(
        messages, message_id, thread_id, access_token, team_id, slack_client
    )
    return ThreadContextResult.success(thread_text)


def _build_thread_text(
    messages: list[dict[str, Any]],
    message_id: str,
    thread_id: str,
    access_token: str,
    team_id: str | None,
    slack_client: WebClient,
) -> str:
    """Build the thread text from messages."""
    msg_text = messages[0].get("text", "")
    msg_sender = messages[0].get("user", "")
    thread_text = f"<@{msg_sender}>: {msg_text}"

    thread_text += "\n\nReplies:"
    if thread_id == message_id:
        message_id_idx = 0
    else:
        message_id_idx = next(
            (i for i, msg in enumerate(messages) if msg.get("ts") == message_id), 0
        )
        if not message_id_idx:
            return thread_text

        start_idx = max(1, message_id_idx - SLACK_THREAD_CONTEXT_WINDOW)

        if start_idx > 1:
            thread_text += "\n..."

        for i in range(start_idx, message_id_idx):
            msg_text = messages[i].get("text", "")
            msg_sender = messages[i].get("user", "")
            thread_text += f"\n\n<@{msg_sender}>: {msg_text}"

        msg_text = messages[message_id_idx].get("text", "")
        msg_sender = messages[message_id_idx].get("user", "")
        thread_text += f"\n\n<@{msg_sender}>: {msg_text}"

    # Add following replies
    len_replies = 0
    for msg in messages[message_id_idx + 1 :]:
        msg_text = msg.get("text", "")
        msg_sender = msg.get("user", "")
        reply = f"\n\n<@{msg_sender}>: {msg_text}"
        thread_text += reply

        len_replies += len(reply)
        if len_replies >= DOC_EMBEDDING_CONTEXT_SIZE * 4:
            thread_text += "\n..."
            break

    # Replace user IDs with names using cached lookups
    userids: set[str] = set(re.findall(r"<@([A-Z0-9]+)>", thread_text))

    if team_id:
        user_profiles = batch_get_user_profiles(access_token, team_id, userids)
        for userid, name in user_profiles.items():
            thread_text = thread_text.replace(f"<@{userid}>", name)
    else:
        for userid in userids:
            try:
                response = slack_client.users_profile_get(user=userid)
                response.validate()
                profile: dict[str, Any] = response.get("profile", {})
                user_name: str | None = profile.get("real_name") or profile.get("email")
            except SlackApiError as e:
                if "user_not_found" in str(e):
                    logger.debug(
                        f"User {userid} not found (likely deleted/deactivated)"
                    )
                else:
                    logger.warning(f"Could not fetch profile for user {userid}: {e}")
                continue
            if not user_name:
                continue
            thread_text = thread_text.replace(f"<@{userid}>", user_name)

    return thread_text


def fetch_thread_contexts_with_rate_limit_handling(
    slack_messages: list[SlackMessage],
    access_token: str,
    team_id: str | None,
    batch_size: int = SLACK_THREAD_CONTEXT_BATCH_SIZE,
    max_messages: int | None = MAX_SLACK_THREAD_CONTEXT_MESSAGES,
) -> list[str]:
    """
    Fetch thread contexts in controlled batches, stopping on rate limit.

    Distinguishes between error types:
    - Rate limit (429): Stop processing further batches
    - Other errors: Continue processing (graceful degradation)

    Args:
        slack_messages: Messages to fetch thread context for (should be sorted by relevance)
        access_token: Slack OAuth token
        team_id: Slack team ID for user profile caching
        batch_size: Number of concurrent API calls per batch
        max_messages: Maximum messages to fetch thread context for (None = no limit)

    Returns:
        List of thread texts, one per input message.
        Messages beyond max_messages or after rate limit get their original text.
    """
    if not slack_messages:
        return []

    # Limit how many messages we fetch thread context for (if max_messages is set)
    if max_messages and max_messages < len(slack_messages):
        messages_for_context = slack_messages[:max_messages]
        messages_without_context = slack_messages[max_messages:]
    else:
        messages_for_context = slack_messages
        messages_without_context = []

    logger.info(
        f"Fetching thread context for {len(messages_for_context)} of {len(slack_messages)} messages "
        f"(batch_size={batch_size}, max={max_messages or 'unlimited'})"
    )

    results: list[str] = []
    rate_limited = False
    total_batches = (len(messages_for_context) + batch_size - 1) // batch_size
    rate_limit_batch = 0

    # Process in batches
    for i in range(0, len(messages_for_context), batch_size):
        current_batch = i // batch_size + 1

        if rate_limited:
            # Skip remaining batches, use original message text
            remaining = messages_for_context[i:]
            skipped_batches = total_batches - rate_limit_batch
            logger.warning(
                f"Slack rate limit: skipping {len(remaining)} remaining messages "
                f"({skipped_batches} of {total_batches} batches). "
                f"Successfully enriched {len(results)} messages before rate limit."
            )
            results.extend([msg.text for msg in remaining])
            break

        batch = messages_for_context[i : i + batch_size]

        # _fetch_thread_context returns ThreadContextResult (never raises)
        # allow_failures=True is a safety net for any unexpected exceptions
        batch_results: list[ThreadContextResult | None] = (
            run_functions_tuples_in_parallel(
                [
                    (
                        _fetch_thread_context,
                        (msg, access_token, team_id),
                    )
                    for msg in batch
                ],
                allow_failures=True,
                max_workers=batch_size,
            )
        )

        # Process results - ThreadContextResult tells us exactly what happened
        for j, result in enumerate(batch_results):
            if result is None:
                # Unexpected exception (shouldn't happen) - use original text, stop
                logger.error(f"Unexpected None result for message {j} in batch")
                results.append(batch[j].text)
                rate_limited = True
                rate_limit_batch = current_batch
            elif result.is_rate_limited:
                # Rate limit hit - use original text, stop further batches
                results.append(result.text)
                rate_limited = True
                rate_limit_batch = current_batch
            else:
                # Success or recoverable error - use the text (enriched or original)
                results.append(result.text)

        if rate_limited:
            logger.warning(
                f"Slack rate limit (429) hit at batch {current_batch}/{total_batches} "
                f"while fetching thread context. Stopping further API calls."
            )

    # Add original text for messages we didn't fetch context for
    results.extend([msg.text for msg in messages_without_context])

    return results


def convert_slack_score(slack_score: float) -> float:
    """
    Convert slack score to a score between 0 and 1.
    Will affect UI ordering and LLM ordering, but not the pruning.
    I.e., should have very little effect on the search/answer quality.
    """
    return max(0.0, min(1.0, slack_score / 90_000))


@log_function_time(print_only=True)
def slack_retrieval(
    query: ChunkIndexRequest,
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
        logger.debug("No entity configuration found, using defaults")
    else:
        logger.debug(f"Using entity configuration: {entities}")

    # Extract limit from entity config if not explicitly provided
    query_limit = limit
    if entities:
        try:
            parsed_entities = SlackEntities(**entities)
            if limit is None:
                query_limit = parsed_entities.max_messages_per_query
                logger.debug(f"Using max_messages_per_query from config: {query_limit}")
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
    llm = get_default_llm()
    query_strings = build_slack_queries(query, llm, entities, available_channels)

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
            logger.debug(
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
                channel_metadata_dict,
            ),
        )
        for query_string in query_strings
    ]

    # If include_dm is True AND we're not already searching all channels,
    # add additional searches without channel filters.
    # This allows searching DMs/group DMs while still searching the specified channels.
    # Skip this if search_all_channels is already True (would be duplicate queries).
    if (
        entities
        and entities.get("include_dm")
        and not entities.get("search_all_channels")
    ):
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
                        channel_metadata_dict,
                    ),
                )
            )

    # Execute searches in parallel
    results = run_functions_tuples_in_parallel(search_tasks)

    # Calculate stats for consolidated logging
    total_raw_messages = sum(len(r.messages) for r in results)

    # Merge and post-filter results
    slack_messages, docid_to_message, query_filtered_channels = merge_slack_messages(
        results
    )
    messages_after_dedup = len(slack_messages)

    # Post-filter by channel type (DM, private channel, etc.)
    # NOTE: We must post-filter because Slack's search.messages API only supports
    # filtering by channel NAME (via in:#channel syntax), not by channel TYPE.
    # There's no way to specify "only public channels" or "exclude DMs" in the query.
    # Start with channels filtered during query execution, then add post-filter channels
    filtered_out_channels: set[str] = set(query_filtered_channels)
    if entities and team_id:
        # Use pre-fetched channel metadata to avoid cache misses
        # Pass it directly instead of relying on Redis cache

        filtered_messages = []
        for msg in slack_messages:
            # Pass pre-fetched metadata to avoid cache lookups
            channel_type = get_channel_type(
                channel_id=msg.channel_id,
                channel_metadata=channel_metadata_dict,
            )
            if should_include_message(channel_type, entities):
                filtered_messages.append(msg)
            else:
                # Track unique channel name for summary
                channel_name = msg.metadata.get("channel", msg.channel_id)
                filtered_out_channels.add(f"{channel_name}({msg.channel_id})")

        slack_messages = filtered_messages

    slack_messages = slack_messages[: limit or len(slack_messages)]

    # Log consolidated summary with request ID for correlation
    request_id = (
        slack_event_context.message_ts[:10]
        if slack_event_context and slack_event_context.message_ts
        else "no-ctx"
    )
    logger.info(
        f"[req:{request_id}] Slack federated search: {len(search_tasks)} queries, "
        f"{total_raw_messages} raw msgs -> {messages_after_dedup} after dedup -> "
        f"{len(slack_messages)} final"
        + (
            f", filtered channels: {sorted(filtered_out_channels)}"
            if filtered_out_channels
            else ""
        )
    )

    if not slack_messages:
        return []

    # Fetch thread context with rate limit handling and message limiting
    # Messages are already sorted by relevance (slack_score), so top N get full context
    thread_texts = fetch_thread_contexts_with_rate_limit_handling(
        slack_messages=slack_messages,
        access_token=access_token,
        team_id=team_id,
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
