"""Resource units (RU) for each app over sliding windows, and the pause that
follows a throttled call."""

import math
from collections import deque
from typing import Literal

from pydantic import BaseModel

from .settings import QuotaSettings

RuCost = Literal[
    "item_get",
    "delta_with_token",
    "delta_without_token",
    "download",
    "download_url",
    "list_children",
    "permission",
    "rest",
    "other",
    "none",
]


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


class ThrottleDecision(BaseModel):
    scope: Literal["minute", "day", "pause"]
    # Seconds for the Retry-After header. None sends no header.
    retry_after: int | None


class _AppUsage:
    def __init__(self, settings: QuotaSettings) -> None:
        self.minute = SlidingWindow(settings.window_seconds)
        self.day = SlidingWindow(settings.day_window_seconds)
        self.pause_until = 0.0


class RuTracker:
    def __init__(self, settings: QuotaSettings) -> None:
        self.settings = settings
        self._apps: dict[str, _AppUsage] = {}

    def update_settings(self, settings: QuotaSettings) -> None:
        if (
            settings.window_seconds != self.settings.window_seconds
            or settings.day_window_seconds != self.settings.day_window_seconds
        ):
            self._apps.clear()
        self.settings = settings

    def reset(self) -> None:
        self._apps.clear()

    def cost(self, cost: RuCost) -> int:
        s = self.settings
        return {
            "item_get": s.item_get_ru,
            "delta_with_token": s.delta_with_token_ru,
            "delta_without_token": s.delta_without_token_ru,
            "download": s.download_ru,
            "download_url": s.download_url_ru,
            "list_children": s.list_children_ru,
            "permission": s.permission_ru,
            "rest": s.rest_ru,
            "other": s.other_ru,
            "none": 0,
        }[cost]

    def consume(self, app: str, amount: int, now: float) -> ThrottleDecision | None:
        """Takes `amount` RU from the app's budget, or returns why the call is
        throttled. A throttled call uses its RU when count_throttled_calls is
        set."""
        s = self.settings
        if not s.enabled:
            return None
        usage = self._apps.get(app)
        if usage is None:
            usage = self._apps[app] = _AppUsage(s)

        decision: ThrottleDecision | None = None
        if now < usage.pause_until:
            decision = ThrottleDecision(
                scope="pause", retry_after=max(1, math.ceil(usage.pause_until - now))
            )
        elif usage.minute.total(now) + amount > s.ru_per_minute * (
            s.window_seconds / 60.0
        ):
            decision = ThrottleDecision(scope="minute", retry_after=None)
        elif s.ru_per_day is not None and usage.day.total(now) + amount > s.ru_per_day:
            decision = ThrottleDecision(scope="day", retry_after=None)

        if decision is None or s.count_throttled_calls:
            usage.minute.add(now, amount)
            usage.day.add(now, amount)
        if decision is not None and decision.scope != "pause":
            decision.retry_after = s.retry_after_seconds
            if s.retry_after_seconds is not None:
                usage.pause_until = now + s.retry_after_seconds
        return decision

    def usage(self, now: float) -> dict[str, object]:
        """RU in the current windows, for each app."""
        s = self.settings
        return {
            app: {
                "ru_in_minute_window": usage.minute.total(now),
                "ru_in_day_window": usage.day.total(now),
                "ru_per_minute": s.ru_per_minute,
                "ru_per_day": s.ru_per_day,
                "pause_seconds_left": round(max(0.0, usage.pause_until - now), 2),
            }
            for app, usage in self._apps.items()
        }
