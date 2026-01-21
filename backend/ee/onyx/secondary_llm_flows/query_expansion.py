import re

from ee.onyx.prompts.query_expansion import KEYWORD_EXPANSION_PROMPT
from onyx.llm.interfaces import LLM
from onyx.llm.models import LanguageModelInput
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import UserMessage
from onyx.llm.utils import llm_response_to_string
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Pattern to remove common LLM artifacts: brackets, quotes, list markers, etc.
CLEANUP_PATTERN = re.compile(r'[\[\]"\'`]')


def _clean_keyword_line(line: str) -> str:
    """Clean a keyword line by removing common LLM artifacts.

    Removes brackets, quotes, and other characters that LLMs may accidentally
    include in their output.
    """
    # Remove common artifacts
    cleaned = CLEANUP_PATTERN.sub("", line)
    # Remove leading list markers like "1.", "2.", "-", "*"
    cleaned = re.sub(r"^\s*(?:\d+[\.\)]\s*|[-*]\s*)", "", cleaned)
    return cleaned.strip()


def expand_keywords(
    user_query: str,
    llm: LLM,
) -> list[str]:
    """Expand a user query into multiple keyword-only queries for BM25 search.

    Uses an LLM to generate keyword-based search queries that capture different
    aspects of the user's search intent. Returns only the expanded queries,
    not the original query.

    Args:
        user_query: The original search query from the user
        llm: Language model to use for keyword expansion

    Returns:
        List of expanded keyword queries (excluding the original query).
        Returns empty list if expansion fails or produces no useful expansions.
    """
    messages: LanguageModelInput = [
        UserMessage(content=KEYWORD_EXPANSION_PROMPT.format(user_query=user_query))
    ]

    try:
        response = llm.invoke(
            prompt=messages,
            reasoning_effort=ReasoningEffort.OFF,
            # Limit output - we only expect a few short keyword queries
            max_tokens=150,
        )

        content = llm_response_to_string(response).strip()

        if not content:
            logger.warning("Keyword expansion returned empty response.")
            return []

        # Parse response - each line is a separate keyword query
        # Clean each line to remove LLM artifacts and drop empty lines
        parsed_queries = []
        for line in content.strip().split("\n"):
            cleaned = _clean_keyword_line(line)
            if cleaned:
                parsed_queries.append(cleaned)

        if not parsed_queries:
            logger.warning("Keyword expansion parsing returned no queries.")
            return []

        # Filter out duplicates and queries that match the original
        expanded_queries: list[str] = []
        seen_lower: set[str] = {user_query.lower()}
        for query in parsed_queries:
            query_lower = query.lower()
            if query_lower not in seen_lower:
                seen_lower.add(query_lower)
                expanded_queries.append(query)

        logger.debug(f"Keyword expansion generated {len(expanded_queries)} queries")
        return expanded_queries

    except Exception as e:
        logger.warning(f"Keyword expansion failed: {e}")
        return []
