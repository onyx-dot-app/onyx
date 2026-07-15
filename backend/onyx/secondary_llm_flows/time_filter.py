import re
from datetime import datetime
from datetime import time
from datetime import timedelta
from datetime import timezone
from enum import StrEnum

from dateutil.relativedelta import relativedelta
from pydantic import BaseModel

from onyx.configs.constants import MessageType
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import TimeRange
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


class DocumentTimeField(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class TimeFilter(BaseModel):
    """The document date the conversation scopes on (created vs updated) and
    the inclusive (start, end) window; either bound may be None (open)."""

    field: DocumentTimeField
    start: datetime | None = None
    end: datetime | None = None

    def apply_to(self, filters: BaseFilters) -> BaseFilters:
        """Return a copy of `filters` with this window intersected onto the
        matching range field, so the inferred window can narrow but never widen
        a caller-selected restriction. A disjoint inferred window is dropped —
        the explicit range wins over silently matching nothing."""
        filters = filters.model_copy()
        window = TimeRange(start=self.start, end=self.end)
        if self.field is DocumentTimeField.CREATED_AT:
            merged = window.intersect(filters.created_at_range)
            if not merged.is_empty():
                filters.created_at_range = merged
        else:
            merged = window.intersect(filters.updated_at_range)
            if not merged.is_empty():
                filters.updated_at_range = merged
        return filters


# The model's "(start, end)" output; each side is one comma/paren-free token.
_TIME_FILTER_PAIR_RE = re.compile(r"\(\s*([^(),]+?)\s*,\s*([^(),]+?)\s*\)")

# The date field the model prefixes its pair with ("created (...)" /
# "updated (...)"). Absent / anything else defaults to updated.
_TIME_FILTER_FIELD_RE = re.compile(r"\b(created|updated)\b", re.IGNORECASE)

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


def _parse_absolute_date(token: str) -> datetime | None:
    """Parse the prompt's promised YYYY-MM-DD format; anything else fails open
    so a partial date can't silently inherit today's month/day."""
    try:
        return datetime.strptime(token, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_bound(token: str, now: datetime) -> datetime | None:
    """Parse one side of the pair: a date, a relative offset, or None."""
    token = token.strip().strip("'\"")
    if token.lower() in ("none", "null"):
        return None
    relative = _resolve_relative_bound(token, now)
    if relative is not None:
        return relative
    return _parse_absolute_date(token)


def _parse_time_decision(
    content: str | None, now: datetime | None = None
) -> TimeFilter | None:
    """Parse the model's "<field> (start, end)" output into a TimeFilter; the
    field defaults to updated when absent. Returns None on anything unparseable,
    or when neither bound is set, so the caller searches across all time."""
    now = now or datetime.now(timezone.utc)
    if not content:
        return None
    # search() tolerates code fences / stray text around the pair.
    match = _TIME_FILTER_PAIR_RE.search(content)
    if match is None:
        logger.warning("Time filter output was not a (start, end) pair: %s", content)
        return None

    # Documents live in the past: a start after today is a model error, and an
    # end at/after today (e.g. wrongly closing an open-ended range) means
    # unbounded. A start of today stays — that's a "today" window.
    start = _parse_bound(match.group(1), now)
    if start is not None and start.date() > now.date():
        start = None
    # Push the upper bound to end-of-day so it includes the whole named day.
    end_day = _parse_bound(match.group(2), now)
    if end_day is not None and end_day.date() >= now.date():
        end_day = None
    end = (
        datetime.combine(end_day.date(), time.max, tzinfo=timezone.utc)
        if end_day
        else None
    )
    if start is None and end is None:
        return None

    # The field keyword precedes the pair; default to updated (the over-
    # extending best guess) when the model omits or garbles it.
    field_match = _TIME_FILTER_FIELD_RE.search(content[: match.start()])
    field = (
        DocumentTimeField.CREATED_AT
        if field_match is not None and field_match.group(1).lower() == "created"
        else DocumentTimeField.UPDATED_AT
    )
    return TimeFilter(field=field, start=start, end=end)


def decide_time_filter(
    history: list[ChatMinimalTextMessage],
    llm: LLM,
) -> TimeFilter | None:
    """Detect, in one LLM call, the time scope the conversation restricts this
    turn's internal search to: which document date it is about (created vs
    updated) plus the inclusive window. Returns None — search across all time —
    when no time is referenced, and fails open to None on any error."""
    user_turns = [
        msg.message.strip()
        for msg in history
        if msg.message_type == MessageType.USER and msg.message.strip()
    ]
    if not user_turns:
        return None
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
        return _parse_time_decision(content, now)
    except Exception:
        logger.exception("Time filter decision failed; searching across all time")
        return None
