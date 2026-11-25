"""Numbers of the calls the server answered since the last reset."""

import time
from typing import Any

from pydantic import BaseModel


class OpStats(BaseModel):
    count: int = 0
    throttled: int = 0
    errors: int = 0
    ru: int = 0
    bytes: int = 0
    total_ms: float = 0.0
    # Calls with $expand=canvasLayout (site page operations only).
    canvas_expanded: int = 0


class CallRecord(BaseModel):
    op: str
    status: int
    ru: int = 0
    nbytes: int = 0
    duration_ms: float = 0.0
    # "<tenant id>/<client id>", or None for a call with no app.
    app: str | None = None
    throttled: bool = False
    during_pause: bool = False
    downloaded_item_id: str | None = None
    canvas_expanded: bool = False
    user_agent: str | None = None


class Stats:
    def __init__(self) -> None:
        self.inflight = 0
        self.reset()

    def reset(self) -> None:
        """Clears the numbers. Requests in flight stay counted, so their
        finish does not make the count negative. Their time counts from now."""
        self.reset_at = time.monotonic()
        self.first_at: float | None = self.reset_at if self.inflight else None
        self.last_at: float | None = None
        self.ops: dict[str, OpStats] = {}
        self.statuses: dict[int, int] = {}
        self.ru_by_app: dict[str, int] = {}
        self.throttled_by_app: dict[str, int] = {}
        self.calls_during_pause: dict[str, int] = {}
        self.item_downloads: dict[str, int] = {}
        self.user_agents: dict[str, int] = {}
        self.max_inflight = self.inflight
        self._inflight_area = 0.0
        self._inflight_changed_at = self.reset_at

    def _move_inflight(self, now: float, delta: int) -> None:
        self._inflight_area += self.inflight * (now - self._inflight_changed_at)
        self._inflight_changed_at = now
        self.inflight += delta
        self.max_inflight = max(self.max_inflight, self.inflight)

    def http_started(self) -> None:
        now = time.monotonic()
        if self.first_at is None:
            self.first_at = now
            self._inflight_changed_at = now
            self._inflight_area = 0.0
        self._move_inflight(now, 1)

    def http_finished(self) -> None:
        now = time.monotonic()
        self._move_inflight(now, -1)
        self.last_at = now

    def record(self, call: CallRecord) -> None:
        stats = self.ops.setdefault(call.op, OpStats())
        stats.count += 1
        stats.total_ms += call.duration_ms
        stats.bytes += call.nbytes
        stats.ru += call.ru
        self.statuses[call.status] = self.statuses.get(call.status, 0) + 1
        if call.user_agent is not None:
            self.user_agents[call.user_agent] = (
                self.user_agents.get(call.user_agent, 0) + 1
            )
        if call.app is not None and call.ru:
            self.ru_by_app[call.app] = self.ru_by_app.get(call.app, 0) + call.ru
        if call.canvas_expanded:
            stats.canvas_expanded += 1
        if call.throttled:
            stats.throttled += 1
            if call.app is not None:
                self.throttled_by_app[call.app] = (
                    self.throttled_by_app.get(call.app, 0) + 1
                )
                if call.during_pause:
                    self.calls_during_pause[call.app] = (
                        self.calls_during_pause.get(call.app, 0) + 1
                    )
            return
        if call.status >= 400:
            stats.errors += 1
        if call.downloaded_item_id is not None and call.status < 300:
            self.item_downloads[call.downloaded_item_id] = (
                self.item_downloads.get(call.downloaded_item_id, 0) + 1
            )

    def snapshot(self, quota_usage: dict[str, object]) -> dict[str, Any]:
        now = time.monotonic()
        # While requests are in flight, the active time runs to now.
        active_end = now if self.inflight > 0 else (self.last_at or now)
        active = active_end - self.first_at if self.first_at is not None else 0.0
        area = self._inflight_area + self.inflight * (now - self._inflight_changed_at)
        minutes = active / 60 if active > 0 else 0.0
        ru = sum(s.ru for s in self.ops.values())
        return {
            "since_reset_seconds": round(now - self.reset_at, 2),
            "active_seconds": round(active, 2),
            "requests": sum(s.count for s in self.ops.values()),
            "throttled": sum(s.throttled for s in self.ops.values()),
            "ru": ru,
            "ru_per_minute": round(ru / minutes, 1) if minutes else 0.0,
            "ru_by_app": dict(sorted(self.ru_by_app.items())),
            "throttled_by_app": dict(sorted(self.throttled_by_app.items())),
            "calls_during_pause": dict(sorted(self.calls_during_pause.items())),
            "calls_during_pause_total": sum(self.calls_during_pause.values()),
            "item_downloads": dict(sorted(self.item_downloads.items())),
            "downloads": sum(self.item_downloads.values()),
            "user_agents": dict(sorted(self.user_agents.items())),
            "max_inflight": self.max_inflight,
            "avg_inflight": round(area / active, 2) if active > 0 else 0.0,
            "statuses": {str(k): v for k, v in sorted(self.statuses.items())},
            "ops": {
                name: {
                    **s.model_dump(),
                    "avg_ms": round(s.total_ms / s.count, 1) if s.count else 0.0,
                }
                for name, s in sorted(self.ops.items())
            },
            "quota_window": quota_usage,
        }
