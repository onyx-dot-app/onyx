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

# Mirrors MAX_SOURCE_FILTER_USER_TURNS in source_filter.py.
MAX_TIME_FILTER_USER_TURNS = 5


# Inclusive (start, end) bounds on a document's last-updated date; None on
# either side means unbounded.
TimeFilter = tuple[datetime | None, datetime | None]

# The model's "(start, end)" output; each side is one comma/paren-free token.
_TIME_FILTER_PAIR_RE = re.compile(r"\(\s*([^(),]+?)\s*,\s*([^(),]+?)\s*\)")

# Signed ISO-8601 duration before today (e.g. "-P15W"), emitted for numeric
# offsets so the model never does date arithmetic itself.
_RELATIVE_BOUND_RE = re.compile(r"^-?\s*P\s*(\d+)\s*([DWMY])$", re.IGNORECASE)


def _resolve_relative_bound(token: str, now: datetime) -> datetime | None:
    """Resolve a duration token to `now` minus N units, or None if not one."""
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
    """Parse one side of the pair: a date, a relative offset, or None."""
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
    """Parse the model's "(start, end)" output into a TimeFilter, failing open
    to (None, None) on anything unparseable."""
    now = now or datetime.now(timezone.utc)
    if not content:
        return (None, None)
    # search() tolerates code fences / stray text around the pair.
    match = _TIME_FILTER_PAIR_RE.search(content)
    if match is None:
        logger.warning("Time filter output was not a (start, end) pair: %s", content)
        return (None, None)

    start = _parse_bound(match.group(1), now)
    # Push the upper bound to end-of-day so it includes the whole named day.
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
    """Detect, in one LLM call, the time window the conversation restricts this
    turn's internal search to. Fails open to (None, None) on any error."""
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
