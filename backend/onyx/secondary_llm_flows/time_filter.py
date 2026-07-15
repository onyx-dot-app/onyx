import re
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from datetime import timezone
from enum import StrEnum

from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from pydantic import BaseModel

from onyx.configs.constants import MessageType
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
    """A conversation-derived time scope for an internal search.

    `field` is the document date the user's phrasing is about — creation time
    ("sent/created/opened in X") vs. update/activity time (anything else).
    `start` / `end` are the inclusive window; either may be None (open).
    `decide_time_filter` returns None when the conversation references no time.
    """

    field: DocumentTimeField
    start: datetime | None = None
    end: datetime | None = None

    def to_filter_ranges(self) -> tuple[TimeRange | None, TimeRange | None]:
        """Map this scope onto (created_at_range, updated_at_range) per
        FILTER_SEMANTICS.md ("Time filtering"): created intent is a plain
        created_at window; updated intent is the best-guess overlap
        (last_updated >= start AND created_at <= end), since edit history is
        unstored — the upper bound must NOT go on last_updated.
        """
        if self.field is DocumentTimeField.CREATED_AT:
            return TimeRange(start=self.start, end=self.end), None
        created = TimeRange(end=self.end) if self.end is not None else None
        updated = TimeRange(start=self.start) if self.start is not None else None
        return created, updated


# The model's "(start, end)" output; each side is one comma/paren-free token.
_TIME_FILTER_PAIR_RE = re.compile(r"\(\s*([^(),]+?)\s*,\s*([^(),]+?)\s*\)")

# The date field the model prefixes its pair with ("created (...)" /
# "updated (...)"). Absent / anything else defaults to updated.
_TIME_FILTER_FIELD_RE = re.compile(r"\b(created|updated)\b", re.IGNORECASE)

# Signed ISO-8601 duration before today (e.g. "-P15W"), emitted for numeric
# offsets so the model never does date arithmetic itself.
_RELATIVE_BOUND_RE = re.compile(r"^-?\s*P\s*(\d+)\s*([DWMY])$", re.IGNORECASE)


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _day_end(day: date) -> datetime:
    return datetime.combine(day, time.max, tzinfo=timezone.utc)


def _relative_token_parts(token: str) -> tuple[int, str] | None:
    """The (amount, unit) of a "-P<N><U>" token, or None if it isn't one."""
    match = _RELATIVE_BOUND_RE.match(token)
    if match is None:
        return None
    return int(match.group(1)), match.group(2).upper()


def _resolve_relative_bound(token: str, now: datetime) -> datetime | None:
    """Resolve a duration token to `now` minus N units, or None if not one."""
    parts = _relative_token_parts(token)
    if parts is None:
        return None
    amount, unit = parts
    if unit == "D":
        return now - timedelta(days=amount)
    if unit == "W":
        return now - timedelta(weeks=amount)
    if unit == "M":
        return now - relativedelta(months=amount)
    return now - relativedelta(years=amount)


def _period_bounds(token: str, now: datetime) -> tuple[datetime, datetime] | None:
    """The calendar period a "-P<N><U>" token lands in, as (start, end): the
    ISO week (Monday-Sunday), calendar month, or calendar year containing `now`
    minus N units; for days, that single day. None if not a relative offset."""
    parts = _relative_token_parts(token)
    anchor_dt = _resolve_relative_bound(token, now)
    if parts is None or anchor_dt is None:
        return None
    anchor = anchor_dt.date()
    _, unit = parts
    if unit == "D":
        return _day_start(anchor), _day_end(anchor)
    if unit == "W":
        monday = anchor - timedelta(days=anchor.weekday())
        return _day_start(monday), _day_end(monday + timedelta(days=6))
    if unit == "M":
        first = anchor.replace(day=1)
        last = (first + relativedelta(months=1)) - timedelta(days=1)
        return _day_start(first), _day_end(last)
    return (
        _day_start(anchor.replace(month=1, day=1)),
        _day_end(anchor.replace(month=12, day=31)),
    )


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
) -> TimeFilter | None:
    """Parse the model's "<field> (start, end)" output into a TimeFilter.

    Bounds are inclusive of whole days: starts are floored to the start of
    their day and ends pushed to the end of theirs. An identical relative token
    on both sides can only mean "the Nth calendar period back" ("(-P1W, -P1W)"
    is the previous week), never a rolling window, so it resolves to that
    period's boundaries. Returns None on anything unparseable, or when neither
    bound is set, so the caller searches across all time.
    """
    now = now or datetime.now(timezone.utc)
    if not content:
        return None
    # search() tolerates code fences / stray text around the pair.
    match = _TIME_FILTER_PAIR_RE.search(content)
    if match is None:
        logger.warning("Time filter output was not a (start, end) pair: %s", content)
        return None

    start_token = match.group(1).strip().strip("'\"")
    end_token = match.group(2).strip().strip("'\"")

    start: datetime | None
    end: datetime | None
    start_parts = _relative_token_parts(start_token)
    period = (
        _period_bounds(start_token, now)
        if start_parts is not None and start_parts == _relative_token_parts(end_token)
        else None
    )
    if period is not None:
        start, end = period
    else:
        start_day = _parse_bound(start_token, now)
        start = _day_start(start_day.date()) if start_day else None
        end_day = _parse_bound(end_token, now)
        end = _day_end(end_day.date()) if end_day else None

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
    except Exception:
        logger.exception("Time filter decision failed; searching across all time")
        return None

    return _parse_time_decision(content, now)
