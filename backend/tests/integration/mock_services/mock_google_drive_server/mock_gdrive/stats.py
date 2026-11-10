"""Throughput numbers of the calls the server answered since the last reset."""

import time
from typing import Any

from pydantic import BaseModel


class OpStats(BaseModel):
    count: int = 0
    rate_limited: int = 0
    errors: int = 0
    units: int = 0
    bytes: int = 0
    total_ms: float = 0.0


class MinuteStats(BaseModel):
    requests: int = 0
    units: int = 0
    rate_limited: int = 0
    content_fetches: int = 0


class Stats:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.reset_at = time.monotonic()
        self.first_at: float | None = None
        self.last_at: float | None = None
        self.ops: dict[str, OpStats] = {}
        self.statuses: dict[int, int] = {}
        self.minutes: dict[int, MinuteStats] = {}
        self.user_units: dict[str, int] = {}
        self.content_file_ids: set[str] = set()
        self.content_fetches = 0
        self.docs_api_file_ids: set[str] = set()
        self.inflight = 0
        self.max_inflight = 0
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

    def record(
        self,
        *,
        op: str,
        status: int,
        units: int,
        nbytes: int,
        duration_ms: float,
        user: str | None,
        rate_limited: bool,
        content_file_id: str | None,
    ) -> None:
        now = time.monotonic()
        stats = self.ops.setdefault(op, OpStats())
        stats.count += 1
        stats.total_ms += duration_ms
        stats.bytes += nbytes
        self.statuses[status] = self.statuses.get(status, 0) + 1
        minute = int((now - (self.first_at or now)) // 60)
        bucket = self.minutes.setdefault(minute, MinuteStats())
        bucket.requests += 1
        if rate_limited:
            stats.rate_limited += 1
            bucket.rate_limited += 1
            return
        if status >= 400:
            stats.errors += 1
        stats.units += units
        bucket.units += units
        if user:
            self.user_units[user] = self.user_units.get(user, 0) + units
        if content_file_id and status < 400:
            if op == "docs.documents.get":
                self.docs_api_file_ids.add(content_file_id)
            else:
                self.content_fetches += 1
                bucket.content_fetches += 1
                self.content_file_ids.add(content_file_id)

    def snapshot(self, quota_usage: dict[str, object]) -> dict[str, Any]:
        now = time.monotonic()
        active = (
            (self.last_at or now) - self.first_at if self.first_at is not None else 0.0
        )
        area = self._inflight_area + self.inflight * (now - self._inflight_changed_at)
        minutes = active / 60 if active > 0 else 0.0
        requests = sum(s.count for s in self.ops.values())
        units = sum(s.units for s in self.ops.values())
        rate_limited = sum(s.rate_limited for s in self.ops.values())
        peak_units = max((m.units for m in self.minutes.values()), default=0)
        return {
            "since_reset_seconds": round(now - self.reset_at, 2),
            "active_seconds": round(active, 2),
            "requests": requests,
            "rate_limited": rate_limited,
            "units": units,
            "units_per_minute": round(units / minutes, 1) if minutes else 0.0,
            "peak_minute_units": peak_units,
            "unique_content_files": len(self.content_file_ids),
            "content_fetches": self.content_fetches,
            "docs_api_files": len(self.docs_api_file_ids),
            "content_files_per_minute": (
                round(len(self.content_file_ids) / minutes, 1) if minutes else 0.0
            ),
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
            "top_user_units": dict(
                sorted(self.user_units.items(), key=lambda kv: kv[1], reverse=True)[:10]
            ),
            "timeline": [
                {"minute": minute, **bucket.model_dump()}
                for minute, bucket in sorted(self.minutes.items())
            ],
            "quota_window": quota_usage,
        }
