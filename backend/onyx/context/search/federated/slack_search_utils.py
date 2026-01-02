import fnmatch
import json
import re
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from pydantic import ValidationError

from onyx.configs.app_configs import MAX_SLACK_QUERY_EXPANSIONS
from onyx.context.search.federated.models import ChannelMetadata
from onyx.context.search.models import ChunkIndexRequest
from onyx.federated_connectors.slack.models import SlackEntities
from onyx.llm.interfaces import LLM
from onyx.llm.utils import llm_response_to_string
from onyx.onyxbot.slack.models import ChannelType
from onyx.prompts.federated_search import SLACK_DATE_EXTRACTION_PROMPT
from onyx.prompts.federated_search import SLACK_QUERY_EXPANSION_PROMPT
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Constants for date extraction heuristics
DEFAULT_RECENCY_DAYS = 7
DEFAULT_LATELY_DAYS = 14
DAYS_PER_WEEK = 7
DAYS_PER_MONTH = 30
MAX_CONTENT_WORDS = 3

# Punctuation to strip from words during analysis
WORD_PUNCTUATION = ".,!?;:\"'#"

RECENCY_KEYWORDS = ["recent", "latest", "newest", "last"]

# All Slack channel types for fetching metadata
ALL_CHANNEL_TYPES = [
    ChannelType.PUBLIC_CHANNEL.value,
    ChannelType.IM.value,
    ChannelType.MPIM.value,
    ChannelType.PRIVATE_CHANNEL.value,
]

# Map Slack API scopes to their corresponding channel types
# This is used for graceful degradation when scopes are missing
SCOPE_TO_CHANNEL_TYPE_MAP = {
    "mpim:read": ChannelType.MPIM.value,
    "mpim:history": ChannelType.MPIM.value,
    "im:read": ChannelType.IM.value,
    "im:history": ChannelType.IM.value,
    "groups:read": ChannelType.PRIVATE_CHANNEL.value,
    "groups:history": ChannelType.PRIVATE_CHANNEL.value,
    "channels:read": ChannelType.PUBLIC_CHANNEL.value,
    "channels:history": ChannelType.PUBLIC_CHANNEL.value,
}


def get_channel_type_for_missing_scope(scope: str) -> str | None:
    """Get the channel type that requires a specific Slack scope.

    Args:
        scope: The Slack API scope (e.g., 'mpim:read', 'im:history')

    Returns:
        The channel type string if scope is recognized, None otherwise

    Examples:
        >>> get_channel_type_for_missing_scope('mpim:read')
        'mpim'
        >>> get_channel_type_for_missing_scope('im:read')
        'im'
        >>> get_channel_type_for_missing_scope('unknown:scope')
        None
    """
    return SCOPE_TO_CHANNEL_TYPE_MAP.get(scope)


def _parse_llm_code_block_response(response: str) -> str:
    """Remove code block markers from LLM response if present.

    Handles responses wrapped in triple backticks (```) by removing
    the opening and closing markers.

    Args:
        response: Raw LLM response string

    Returns:
        Cleaned response with code block markers removed
    """
    response_clean = response.strip()
    if response_clean.startswith("```"):
        lines = response_clean.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        response_clean = "\n".join(lines)
    return response_clean


def is_recency_query(query: str) -> bool:
    """Check if a query is primarily about recency (not content + recency).

    Returns True only for pure recency queries like "recent messages" or "latest updates",
    but False for queries with content + recency like "golf scores last saturday".
    """
    # Check if query contains recency keywords
    has_recency_keyword = any(
        re.search(rf"\b{re.escape(keyword)}\b", query, flags=re.IGNORECASE)
        for keyword in RECENCY_KEYWORDS
    )

    if not has_recency_keyword:
        return False

    # Get combined stop words (NLTK + Slack-specific)
    all_stop_words = _get_combined_stop_words()

    # Extract content words (excluding stop words)
    query_lower = query.lower()
    words = query_lower.split()

    # Count content words (not stop words, length > 2)
    content_word_count = 0
    for word in words:
        clean_word = word.strip(WORD_PUNCTUATION)
        if clean_word and len(clean_word) > 2 and clean_word not in all_stop_words:
            content_word_count += 1

    # If query has significant content words (>= 2), it's not a pure recency query
    # Examples:
    # - "recent messages" -> content_word_count = 0 -> pure recency
    # - "golf scores last saturday" -> content_word_count = 3 (golf, scores, saturday) -> not pure recency
    return content_word_count < 2


def extract_date_range_from_query(
    query: str,
    llm: LLM,
    default_search_days: int,
) -> int:
    query_lower = query.lower()

    if re.search(r"\btoday(?:\'?s)?\b", query_lower):
        return 0

    if re.search(r"\byesterday\b", query_lower):
        return min(1, default_search_days)

    # Handle "last [day of week]" - e.g., "last monday", "last saturday"
    days_of_week = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
    for day in days_of_week:
        if re.search(rf"\b(?:last|this)\s+{day}\b", query_lower):
            # Assume last occurrence of that day was within the past week
            return min(DAYS_PER_WEEK, default_search_days)

    match = re.search(r"\b(?:last|past)\s+(\d+)\s+days?\b", query_lower)
    if match:
        days = int(match.group(1))
        return min(days, default_search_days)

    if re.search(r"\b(?:last|past|this)\s+week\b", query_lower):
        return min(DAYS_PER_WEEK, default_search_days)

    match = re.search(r"\b(?:last|past)\s+(\d+)\s+weeks?\b", query_lower)
    if match:
        weeks = int(match.group(1))
        return min(weeks * DAYS_PER_WEEK, default_search_days)

    if re.search(r"\b(?:last|past|this)\s+month\b", query_lower):
        return min(DAYS_PER_MONTH, default_search_days)

    match = re.search(r"\b(?:last|past)\s+(\d+)\s+months?\b", query_lower)
    if match:
        months = int(match.group(1))
        return min(months * DAYS_PER_MONTH, default_search_days)

    if re.search(r"\brecent(?:ly)?\b", query_lower):
        return min(DEFAULT_RECENCY_DAYS, default_search_days)

    if re.search(r"\blately\b", query_lower):
        return min(DEFAULT_LATELY_DAYS, default_search_days)

    try:
        prompt = SLACK_DATE_EXTRACTION_PROMPT.format(query=query)
        response = llm_response_to_string(llm.invoke(prompt))

        response_clean = _parse_llm_code_block_response(response)

        try:
            data = json.loads(response_clean)
            if not isinstance(data, dict):
                logger.debug(
                    f"LLM date extraction returned non-dict response for query: "
                    f"'{query}', using default: {default_search_days} days"
                )
                return default_search_days

            days_back = data.get("days_back")
            if days_back is None:
                logger.debug(
                    f"LLM date extraction returned null for query: '{query}', "
                    f"using default: {default_search_days} days"
                )
                return default_search_days

            if not isinstance(days_back, (int, float)):
                logger.debug(
                    f"LLM date extraction returned non-numeric days_back for "
                    f"query: '{query}', using default: {default_search_days} days"
                )
                return default_search_days

        except json.JSONDecodeError:
            logger.debug(
                f"Failed to parse LLM date extraction response for query: '{query}' "
                f"(response: '{response_clean}'), "
                f"using default: {default_search_days} days"
            )
            return default_search_days

        return min(int(days_back), default_search_days)

    except Exception as e:
        logger.warning(f"Error extracting date range with LLM for query '{query}': {e}")
        return default_search_days


def matches_exclude_pattern(channel_name: str, patterns: list[str]) -> bool:
    if not patterns:
        return False

    channel_norm = channel_name.lower().strip().lstrip("#")

    for pattern in patterns:
        pattern_norm = pattern.lower().strip().lstrip("#")
        if fnmatch.fnmatch(channel_norm, pattern_norm):
            return True

    return False


def build_channel_query_filter(
    parsed_entities: SlackEntities | dict[str, Any],
    available_channels: list[str] | None = None,
) -> str:
    # Parse entities if dict
    try:
        if isinstance(parsed_entities, dict):
            entities = SlackEntities(**parsed_entities)
        else:
            entities = parsed_entities
    except ValidationError:
        return ""

    search_all_channels = entities.search_all_channels

    if search_all_channels:
        if not entities.exclude_channels:
            return ""

        # Can't apply exclusions without available_channels
        if not available_channels:
            return ""

        excluded_channels = [
            ch
            for ch in available_channels
            if matches_exclude_pattern(ch, entities.exclude_channels)
        ]
        normalized_excluded = [ch.lstrip("#") for ch in excluded_channels]

        exclusion_filters = [f"-in:#{channel}" for channel in normalized_excluded]
        return " ".join(exclusion_filters)

    if not entities.channels:
        return ""

    included_channels: list[str] = []
    for pattern in entities.channels:
        pattern_norm = pattern.lstrip("#")
        if "*" in pattern_norm or "?" in pattern_norm:
            # Glob patterns require available_channels
            if available_channels:
                matching = [
                    ch
                    for ch in available_channels
                    if fnmatch.fnmatch(ch.lstrip("#").lower(), pattern_norm.lower())
                ]
                included_channels.extend(matching)
        else:
            # Exact match: use directly or verify against available_channels
            if not available_channels or pattern_norm in [
                ch.lstrip("#") for ch in available_channels
            ]:
                included_channels.append(pattern_norm)

    # Apply exclusions to included channels
    if entities.exclude_channels:
        included_channels = [
            ch
            for ch in included_channels
            if not matches_exclude_pattern(ch, entities.exclude_channels)
        ]

    if not included_channels:
        return ""

    normalized_channels = [ch.lstrip("#") for ch in included_channels]
    filters = [f"in:#{channel}" for channel in normalized_channels]
    return " ".join(filters)


def get_channel_type(
    channel_info: dict[str, Any] | None = None,
    channel_id: str | None = None,
    channel_metadata: dict[str, ChannelMetadata] | None = None,
) -> ChannelType:
    """
    Determine channel type from channel info dict or by looking up channel_id.

    Args:
        channel_info: Channel info dict from Slack API (direct mode)
        channel_id: Channel ID to look up (lookup mode)
        channel_metadata: Pre-fetched metadata dict (for lookup mode)

    Returns:
        ChannelType enum
    """
    if channel_info is not None:
        if channel_info.get("is_im"):
            return ChannelType.IM
        if channel_info.get("is_mpim"):
            return ChannelType.MPIM
        if channel_info.get("is_private"):
            return ChannelType.PRIVATE_CHANNEL
        return ChannelType.PUBLIC_CHANNEL

    # Lookup mode: get type from pre-fetched metadata
    if channel_id and channel_metadata:
        ch_meta = channel_metadata.get(channel_id)
        if ch_meta:
            type_str = ch_meta.get("type")
            if type_str == ChannelType.IM.value:
                return ChannelType.IM
            elif type_str == ChannelType.MPIM.value:
                return ChannelType.MPIM
            elif type_str == ChannelType.PRIVATE_CHANNEL.value:
                return ChannelType.PRIVATE_CHANNEL
            return ChannelType.PUBLIC_CHANNEL

    return ChannelType.PUBLIC_CHANNEL


def should_include_message(channel_type: ChannelType, entities: dict[str, Any]) -> bool:
    include_dm = entities.get("include_dm", False)
    include_group_dm = entities.get("include_group_dm", False)
    include_private = entities.get("include_private_channels", False)

    if channel_type == ChannelType.IM:
        return include_dm
    if channel_type == ChannelType.MPIM:
        return include_group_dm
    if channel_type == ChannelType.PRIVATE_CHANNEL:
        return include_private
    return True


def extract_channel_references_from_query(query_text: str) -> set[str]:
    """Extract channel names referenced in the query text.

    Only matches explicit channel references with prepositions or # symbols:
    - "in the office channel"
    - "from the office channel"
    - "in #office"
    - "from #office"

    Does NOT match generic phrases like "slack discussions" or "team channel".

    Args:
        query_text: The user's query text

    Returns:
        Set of channel names (without # prefix)
    """
    channel_references = set()
    query_lower = query_text.lower()

    # Only match channels with explicit prepositions (in/from) or # prefix
    # This prevents false positives like "slack discussions" being interpreted as channel "slack"
    channel_patterns = [
        r"\bin\s+(?:the\s+)?([a-z0-9_-]+)\s+(?:slack\s+)?channels?\b",  # "in the office channel"
        r"\bfrom\s+(?:the\s+)?([a-z0-9_-]+)\s+(?:slack\s+)?channels?\b",  # "from the office channel"
        r"\bin[:\s]*#([a-z0-9_-]+)\b",  # "in #office" or "in:#office"
        r"\bfrom[:\s]*#([a-z0-9_-]+)\b",  # "from #office" or "from:#office"
    ]

    for pattern in channel_patterns:
        matches = re.finditer(pattern, query_lower)
        for match in matches:
            channel_references.add(match.group(1))

    return channel_references


def validate_channel_references(
    channel_references: set[str],
    entities: dict[str, Any],
    available_channels: list[str] | None,
) -> None:
    """Validate that referenced channels exist and are allowed by entity config.

    Args:
        channel_references: Set of channel names extracted from query
        entities: Entity configuration dict
        available_channels: List of available channel names in workspace

    Raises:
        ValueError: If channel doesn't exist, is excluded, or not in inclusion list
    """
    if not channel_references or not entities:
        return

    try:
        parsed_entities = SlackEntities(**entities)

        for channel_name in channel_references:
            # Check if channel exists
            if available_channels is not None:
                # Normalize for comparison (available_channels may or may not have #)
                normalized_available = [
                    ch.lstrip("#").lower() for ch in available_channels
                ]
                if channel_name.lower() not in normalized_available:
                    raise ValueError(
                        f"Channel '{channel_name}' does not exist in your Slack workspace. "
                        f"Please check the channel name and try again."
                    )

            # Check if channel is in exclusion list
            if parsed_entities.exclude_channels:
                if matches_exclude_pattern(
                    channel_name, parsed_entities.exclude_channels
                ):
                    raise ValueError(
                        f"Channel '{channel_name}' is excluded from search by your configuration. "
                        f"Please update your connector settings to search this channel."
                    )

            # Check if channel is in inclusion list (when search_all_channels is False)
            if not parsed_entities.search_all_channels:
                if parsed_entities.channels:
                    # Normalize channel lists for comparison
                    normalized_channels = [
                        ch.lstrip("#").lower() for ch in parsed_entities.channels
                    ]
                    if channel_name.lower() not in normalized_channels:
                        raise ValueError(
                            f"Channel '{channel_name}' is not in your configured channel list. "
                            f"Please update your connector settings to include this channel."
                        )

    except ValidationError:
        # If entities are malformed, skip validation
        pass


def build_channel_override_query(channel_references: set[str], time_filter: str) -> str:
    """Build a Slack query with ONLY channel filters and time filter (no keywords).

    Args:
        channel_references: Set of channel names to search
        time_filter: Time filter string (e.g., " after:2025-11-07")

    Returns:
        Query string with __CHANNEL_OVERRIDE__ marker
    """
    normalized_channels = [ch.lstrip("#") for ch in channel_references]
    channel_filter = " ".join([f"in:#{channel}" for channel in normalized_channels])
    return f"__CHANNEL_OVERRIDE__ {channel_filter}{time_filter}"


# Slack-specific stop words (in addition to standard NLTK stop words)
# These include Slack-specific terms and temporal/recency keywords
SLACK_SPECIFIC_STOP_WORDS = frozenset(
    RECENCY_KEYWORDS
    + [
        "dm",
        "dms",
        "message",
        "messages",
        "channel",
        "channels",
        "slack",
        "post",
        "posted",
        "posting",
        "sent",
    ]
)


def _get_combined_stop_words() -> set[str]:
    """Get combined NLTK + Slack-specific stop words.

    Returns a set of stop words for filtering content words.
    Falls back to just Slack-specific stop words if NLTK is unavailable.

    Note: Currently only supports English stop words. Non-English queries
    may have suboptimal content word extraction. Future enhancement could
    detect query language and load appropriate stop words.
    """
    try:
        from nltk.corpus import stopwords  # type: ignore

        # TODO: Support multiple languages - currently hardcoded to English
        # Could detect language or allow configuration
        nltk_stop_words = set(stopwords.words("english"))
    except Exception:
        # Fallback if NLTK not available
        nltk_stop_words = set()

    return nltk_stop_words | SLACK_SPECIFIC_STOP_WORDS


def extract_content_words_from_recency_query(
    query_text: str, channel_references: set[str]
) -> list[str]:
    """Extract meaningful content words from a recency query.

    Filters out NLTK stop words, Slack-specific terms, channel references, and proper nouns.

    Args:
        query_text: The user's query text
        channel_references: Channel names to exclude from content words

    Returns:
        List of content words (up to MAX_CONTENT_WORDS)
    """
    # Get combined stop words (NLTK + Slack-specific)
    all_stop_words = _get_combined_stop_words()

    words = query_text.split()
    content_words = []

    for word in words:
        clean_word = word.lower().strip(WORD_PUNCTUATION)
        # Skip if it's a channel reference or a stop word
        if clean_word in channel_references:
            continue
        if clean_word and clean_word not in all_stop_words and len(clean_word) > 2:
            clean_word_orig = word.strip(WORD_PUNCTUATION)
            if clean_word_orig.lower() not in all_stop_words:
                content_words.append(clean_word_orig)

    # Filter out proper nouns (capitalized words)
    content_words_filtered = [word for word in content_words if not word[0].isupper()]

    return content_words_filtered[:MAX_CONTENT_WORDS]


def expand_query_with_llm(query_text: str, llm: LLM) -> list[str]:
    """Use LLM to expand query into multiple search variations.

    Args:
        query_text: The user's original query
        llm: LLM instance to use for expansion

    Returns:
        List of rephrased query strings (up to MAX_SLACK_QUERY_EXPANSIONS)
    """
    prompt = SLACK_QUERY_EXPANSION_PROMPT.format(
        query=query_text, max_queries=MAX_SLACK_QUERY_EXPANSIONS
    )

    try:
        response = llm_response_to_string(llm.invoke(prompt))

        response_clean = _parse_llm_code_block_response(response)

        # Split into lines and filter out empty lines
        rephrased_queries = [
            line.strip() for line in response_clean.split("\n") if line.strip()
        ]

        # If no queries generated, use empty query
        if not rephrased_queries:
            logger.debug("No content keywords extracted from query expansion")
            return [""]

        logger.debug(
            f"Expanded query into {len(rephrased_queries)} queries: {rephrased_queries}"
        )
        return rephrased_queries[:MAX_SLACK_QUERY_EXPANSIONS]

    except Exception as e:
        logger.error(f"Error expanding query: {e}")
        return [query_text]


def build_slack_queries(
    query: ChunkIndexRequest,
    llm: LLM,
    entities: dict[str, Any] | None = None,
    available_channels: list[str] | None = None,
) -> list[str]:
    """Build Slack query strings with date filtering and query expansion."""
    default_search_days = 30
    if entities:
        try:
            parsed_entities = SlackEntities(**entities)
            default_search_days = parsed_entities.default_search_days
        except ValidationError as e:
            logger.warning(f"Invalid entities in build_slack_queries: {e}")

    days_back = extract_date_range_from_query(
        query=query.query,
        llm=llm,
        default_search_days=default_search_days,
    )

    # get time filter
    time_filter = ""
    if days_back is not None and days_back >= 0:
        if days_back == 0:
            time_filter = " on:today"
        else:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
            time_filter = f" after:{cutoff_date.strftime('%Y-%m-%d')}"

    # ALWAYS extract channel references from the query (not just for recency queries)
    channel_references = extract_channel_references_from_query(query.query)

    # Validate channel references against available channels and entity config
    # This will raise ValueError if channels are invalid
    if channel_references and entities:
        try:
            validate_channel_references(
                channel_references, entities, available_channels
            )
            logger.info(
                f"Detected and validated channel references: {channel_references}"
            )

            # If valid channels detected, use ONLY those channels with NO keywords
            # Return query with ONLY time filter + channel filter (no keywords)
            return [build_channel_override_query(channel_references, time_filter)]
        except ValueError as e:
            # If validation fails, log the error and continue with normal flow
            logger.warning(f"Channel reference validation failed: {e}")
            channel_references = set()

    # use llm to generate slack queries (use original query to use same keywords as the user)
    if is_recency_query(query.query):
        # For recency queries, extract content words (excluding channel names and stop words)
        content_words = extract_content_words_from_recency_query(
            query.query, channel_references
        )
        rephrased_queries = [" ".join(content_words)] if content_words else [""]
    else:
        # For other queries, use LLM to expand into multiple variations
        rephrased_queries = expand_query_with_llm(query.query, llm)

    # Build final query strings with time filters
    return [
        rephrased_query.strip() + time_filter
        for rephrased_query in rephrased_queries[:MAX_SLACK_QUERY_EXPANSIONS]
    ]
