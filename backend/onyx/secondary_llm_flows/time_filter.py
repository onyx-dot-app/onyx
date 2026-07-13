import re
from datetime import datetime
from datetime import time
from datetime import timedelta
from datetime import timezone

from dateutil.parser import parse
from dateutil.relativedelta import relativedelta

from onyx.configs.constants import MessageType
from onyx.llm.interfaces import LLM
from onyx.llm.models import ChatCompletionMessage
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import UserMessage
from onyx.prompts.filter_extration import TIME_SCOPE_DECISION_PROMPT
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import llm_generation_span
from onyx.tracing.llm_utils import record_llm_response
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Only the most recent user turns carry time intent; older turns add tokens and
# stale directives. Mirrors MAX_SOURCE_FILTER_USER_TURNS in source_filter.py.
MAX_TIME_FILTER_USER_TURNS = 5


# An inclusive (start, end) bound on a document's last-updated date, detected
# from the conversation. Either side may be None, meaning that bound is not
# applied; (None, None) means search across all time.
TimeFilter = tuple[datetime | None, datetime | None]

# Matches the model's "(start, end)" output. Each side is captured as a token
# (a date, a relative "-P<N><unit>" offset, or "None"); neither may contain a
# comma or parenthesis.
_TIME_FILTER_PAIR_RE = re.compile(r"\(\s*([^(),]+?)\s*,\s*([^(),]+?)\s*\)")

# A relative offset the model emits for a plain numeric "N units ago" / "last N
# units" phrasing, as a signed ISO-8601 duration (e.g. "-P15W" = 15 weeks before
# today). Resolved in code so the model never does the error-prone date
# arithmetic itself. The leading minus is optional — every offset we accept is in
# the past. Unit: D=days, W=weeks, M=months, Y=years.
_RELATIVE_BOUND_RE = re.compile(r"^-?\s*P\s*(\d+)\s*([DWMY])$", re.IGNORECASE)


def _resolve_relative_bound(token: str, now: datetime) -> datetime | None:
    """Resolve a "-P<N><unit>" ISO-8601 duration token to an absolute datetime N
    units before `now`, or None if the token isn't a relative offset."""
    match = _RELATIVE_BOUND_RE.match(token)
    if match is None:
        return None
    amount = int(match.group(1))
    unit = match.group(2).upper()
    if unit == "D":
        return now - timedelta(days=amount)
    if unit == "W":
        return now - timedelta(weeks=amount)
    if unit == "M":
        return now - relativedelta(months=amount)
    return now - relativedelta(years=amount)


def best_match_time(time_str: str) -> datetime | None:
    preferred_formats = ["%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"]

    for fmt in preferred_formats:
        try:
            # As we don't know if the user is interacting with the API server from
            # the same timezone as the API server, just assume the queries are UTC time
            # the few hours offset (if any) shouldn't make any significant difference
            dt = datetime.strptime(time_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    # If the above formats don't match, try using dateutil's parser
    try:
        dt = parse(time_str)
        return (
            dt.astimezone(timezone.utc)
            if dt.tzinfo
            else dt.replace(tzinfo=timezone.utc)
        )
    except (ValueError, OverflowError):
        return None


def _parse_bound(token: str, now: datetime) -> datetime | None:
    """Parse one side of the model's pair: a "YYYY-MM-DD" date, a relative
    "-P<N><unit>" ISO-8601 offset (resolved against `now`), or None."""
    token = token.strip().strip("'\"")
    if token.lower() in ("none", "null"):
        return None
    relative = _resolve_relative_bound(token, now)
    if relative is not None:
        return relative
    return best_match_time(token)


def _parse_time_decision(
    content: str | None, now: datetime | None = None
) -> TimeFilter:
    """Parse the model's "(start, end)" output into an inclusive (start, end)
    window. Each side is a "YYYY-MM-DD" date, a "-P<N><unit>" relative offset,
    or None. Returns (None, None) on anything unparseable so the caller searches
    across all time."""
    now = now or datetime.now(timezone.utc)
    if not content:
        return (None, None)
    # Tolerates code fences / stray text some models wrap the pair in.
    match = _TIME_FILTER_PAIR_RE.search(content)
    if match is None:
        logger.warning("Time filter output was not a (start, end) pair: %s", content)
        return (None, None)

    start = _parse_bound(match.group(1), now)
    # The upper bound is inclusive of the whole named day, so push it to the end
    # of that day before comparing against second-granularity document times.
    end_day = _parse_bound(match.group(2), now)
    end = (
        datetime.combine(end_day.date(), time.max, tzinfo=timezone.utc)
        if end_day
        else None
    )

    return (start, end)


def decide_time_filter(
    history: list[ChatMinimalTextMessage],
    llm: LLM,
) -> TimeFilter:
    """Detect, in one LLM call, the time window this turn's internal search should
    be restricted to, from the conversation.

    Returns an inclusive (start, end) window; either side is None to leave that
    bound unset, and (None, None) means search across all time. Fails open to
    (None, None) on any error. The decision is conversation-derived and stable
    across the repeated search cycles within a turn, so the caller computes it
    once and caches it.
    """
    user_turns = [
        msg.message.strip()
        for msg in history
        if msg.message_type == MessageType.USER and msg.message.strip()
    ]
    if not user_turns:
        return (None, None)
    user_turns = user_turns[-MAX_TIME_FILTER_USER_TURNS:]

    last_user_query = user_turns[-1]
    prior_turns = user_turns[:-1]
    conversation_history = (
        "\n".join(prior_turns)
        if prior_turns
        else "N/A, this is the first message in the conversation."
    )
    now = datetime.now(timezone.utc)
    current_day_time_str = now.strftime("%A %B %d, %Y")

    prompt = TIME_SCOPE_DECISION_PROMPT.format(
        current_day_time_str=current_day_time_str,
        conversation_history=conversation_history,
        last_user_query=last_user_query,
    )
    messages: list[ChatCompletionMessage] = [UserMessage(content=prompt)]

    try:
        with llm_generation_span(
            llm=llm,
            flow=LLMFlow.TIME_FILTER_EXTRACTION,
            input_messages=messages,
        ) as span_generation:
            response = llm.invoke(prompt=messages, reasoning_effort=ReasoningEffort.OFF)
            record_llm_response(span_generation, response)
            content = response.choice.message.content
    except Exception:
        logger.exception("Time filter decision failed; searching across all time")
        return (None, None)

    return _parse_time_decision(content, now)
