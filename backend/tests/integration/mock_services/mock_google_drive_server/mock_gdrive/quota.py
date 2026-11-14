"""Per-minute quotas over a sliding window, per project and per user."""

from collections import deque
from typing import Literal

from pydantic import BaseModel

from .settings import QuotaSettings

Bucket = Literal["drive", "docs", "admin"]
UnitCost = Literal["list", "read", "content", "none"]


class SlidingWindow:
    def __init__(self, window_seconds: float) -> None:
        self.window_seconds = window_seconds
        self._events: deque[tuple[float, int]] = deque()
        self._total = 0

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._events and self._events[0][0] <= cutoff:
            self._total -= self._events.popleft()[1]

    def total(self, now: float) -> int:
        self._prune(now)
        return self._total

    def add(self, now: float, amount: int) -> None:
        # Also prunes here: with no limits, nothing calls total().
        self._prune(now)
        self._events.append((now, amount))
        self._total += amount


class RateLimitDecision(BaseModel):
    scope: Literal["project", "user"]
    bucket: Bucket


class QuotaTracker:
    def __init__(self, settings: QuotaSettings) -> None:
        self.settings = settings
        self._project: dict[Bucket, SlidingWindow] = {}
        self._user: dict[tuple[Bucket, str], SlidingWindow] = {}

    def update_settings(self, settings: QuotaSettings) -> None:
        # A count in units means nothing in requests, and the reverse.
        if (
            settings.window_seconds != self.settings.window_seconds
            or settings.model != self.settings.model
        ):
            self._project.clear()
            self._user.clear()
        self.settings = settings

    def reset(self) -> None:
        self._project.clear()
        self._user.clear()

    def unit_cost(self, cost: UnitCost) -> int:
        s = self.settings
        return {
            "list": s.list_units,
            "read": s.read_units,
            "content": s.content_units,
        }.get(cost, 0)

    def _limits(self, bucket: Bucket) -> tuple[int | None, int | None]:
        """(project limit, user limit) per minute for the bucket."""
        s = self.settings
        if s.model == "off":
            return None, None
        if bucket == "docs":
            return s.docs_project_reads_per_minute, s.docs_user_reads_per_minute
        if bucket == "admin":
            return None, s.admin_user_requests_per_minute
        if s.model == "units":
            return s.project_units_per_minute, s.user_units_per_minute
        return s.project_requests_per_minute, s.user_requests_per_minute

    def charge(self, bucket: Bucket, cost: UnitCost) -> int:
        """What a call costs against its bucket's quota."""
        if bucket == "drive" and self.settings.model == "units":
            return self.unit_cost(cost)
        return 1

    def consume(
        self, bucket: Bucket, amount: int, user: str, now: float
    ) -> RateLimitDecision | None:
        """Takes `amount` from the project and user quotas, or returns why it
        cannot. A rejected call takes nothing."""
        window = self.settings.window_seconds
        scale = window / 60.0
        project_limit, user_limit = self._limits(bucket)
        project = self._project.setdefault(bucket, SlidingWindow(window))
        per_user = self._user.setdefault((bucket, user), SlidingWindow(window))
        if (
            project_limit is not None
            and project.total(now) + amount > project_limit * scale
        ):
            return RateLimitDecision(scope="project", bucket=bucket)
        if user_limit is not None and per_user.total(now) + amount > user_limit * scale:
            return RateLimitDecision(scope="user", bucket=bucket)
        project.add(now, amount)
        per_user.add(now, amount)
        return None

    def usage(self, now: float) -> dict[str, object]:
        """Use in the current window, per bucket."""
        result: dict[str, object] = {}
        for bucket, project in self._project.items():
            users = {
                user: w.total(now) for (b, user), w in self._user.items() if b == bucket
            }
            top = sorted(users.items(), key=lambda item: item[1], reverse=True)[:5]
            project_limit, user_limit = self._limits(bucket)
            result[bucket] = {
                "project_in_window": project.total(now),
                "project_limit_per_minute": project_limit,
                "user_limit_per_minute": user_limit,
                "top_users_in_window": dict(top),
            }
        return result
