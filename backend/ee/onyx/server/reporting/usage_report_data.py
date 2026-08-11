"""Aggregates behind the usage report review pack."""

from collections import defaultdict
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.orm import Session

from ee.onyx.db.license import user_counts_toward_seats
from onyx.db.api_key import is_api_key_email_address
from onyx.db.user_usage import DELETED_USER_EXPORT_EMAIL, UsageExportRow
from onyx.db.users import get_all_users

TOP_USER_LIMIT = 10
TOP_ENTRY_LIMIT = 8
DORMANT_USER_LIMIT = 25


class NamedSpend(BaseModel):
    name: str
    cost_cents: float
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class DailySpend(BaseModel):
    day: str  # YYYY-MM-DD
    cost_cents: float
    active_users: int


class UsageReportData(BaseModel):
    period_start: datetime
    period_end: datetime

    total_cost_cents: float
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read_tokens: int

    licensed_users: int
    # Everyone who used it, including people since deactivated, so this can
    # exceed licensed_users. `seated_active_users` is the subset holding a seat.
    active_users: int
    seated_active_users: int
    dormant_users: list[str]

    top_users: list[NamedSpend]
    by_model: list[NamedSpend]
    by_flow: list[NamedSpend]
    daily: list[DailySpend]

    @property
    def dormant_user_count(self) -> int:
        return len(self.dormant_users)

    @property
    def cost_per_active_user_cents(self) -> float:
        if not self.active_users:
            return 0.0
        return self.total_cost_cents / self.active_users

    @property
    def has_usage(self) -> bool:
        return bool(self.daily)


def _top_n(spend_by_name: dict[str, NamedSpend], limit: int) -> list[NamedSpend]:
    ordered = sorted(spend_by_name.values(), key=lambda s: s.cost_cents, reverse=True)
    if len(ordered) <= limit:
        return ordered

    head, tail = ordered[:limit], ordered[limit:]
    # Folding a single entry hides a name and saves no space.
    if len(tail) == 1:
        return ordered

    remainder = NamedSpend(
        name=f"Other ({len(tail)})",
        cost_cents=sum(s.cost_cents for s in tail),
        input_tokens=sum(s.input_tokens for s in tail),
        output_tokens=sum(s.output_tokens for s in tail),
    )
    return head + [remainder]


def build_usage_report_data(
    db_session: Session,
    rows: list[UsageExportRow],
    period_start: datetime,
    period_end: datetime,
) -> UsageReportData:
    """`rows` is the list written to usage_by_user.csv, so the two cannot
    diverge. The period is the admin's requested bounds, for display."""
    by_user: dict[str, NamedSpend] = {}
    by_model: dict[str, NamedSpend] = {}
    by_flow: dict[str, NamedSpend] = {}
    daily_cost: dict[str, float] = defaultdict(float)
    daily_users: dict[str, set[str]] = defaultdict(set)

    total_cost = 0.0
    total_input = 0
    total_output = 0
    total_cache_read = 0
    active_emails: set[str] = set()

    for row in rows:
        for bucket, key in (
            (by_user, row.email),
            (by_model, row.model),
            (by_flow, row.flow),
        ):
            entry = bucket.get(key)
            if entry is None:
                entry = NamedSpend(
                    name=key, cost_cents=0.0, input_tokens=0, output_tokens=0
                )
                bucket[key] = entry
            entry.cost_cents += row.cost_cents
            entry.input_tokens += row.input_tokens
            entry.output_tokens += row.output_tokens

        total_cost += row.cost_cents
        total_input += row.input_tokens
        total_output += row.output_tokens
        total_cache_read += row.cache_read_tokens

        daily_cost[row.day] += row.cost_cents
        # Their spend still counts toward totals so the pack reconciles with the
        # CSV, but neither is a person.
        if row.email != DELETED_USER_EXPORT_EMAIL and not is_api_key_email_address(
            row.email
        ):
            active_emails.add(row.email)
            daily_users[row.day].add(row.email)

    # Must match license enforcement, or this disagrees with what is billed.
    users = get_all_users(db_session, include_api_key_users=False)
    seat_emails = {user.email for user in users if user_counts_toward_seats(user)}
    dormant = sorted(seat_emails - active_emails)

    daily = [
        DailySpend(
            day=day,
            cost_cents=daily_cost[day],
            active_users=len(daily_users[day]),
        )
        for day in sorted(daily_cost)
    ]

    return UsageReportData(
        period_start=period_start,
        period_end=period_end,
        total_cost_cents=total_cost,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_cache_read_tokens=total_cache_read,
        licensed_users=len(seat_emails),
        active_users=len(active_emails),
        seated_active_users=len(active_emails & seat_emails),
        dormant_users=dormant,
        top_users=_top_n(by_user, TOP_USER_LIMIT),
        by_model=_top_n(by_model, TOP_ENTRY_LIMIT),
        by_flow=_top_n(by_flow, TOP_ENTRY_LIMIT),
        daily=daily,
    )
