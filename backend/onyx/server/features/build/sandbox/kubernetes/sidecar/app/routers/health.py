from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe: process is up and serving."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> dict[str, str | float]:
    """Readiness probe: idle tracker initialized, not yet shutting down."""
    tracker = getattr(request.app.state, "idle", None)
    if tracker is None:
        return {"status": "starting"}
    return {
        "status": "ready",
        "seconds_since_last_interaction": tracker.seconds_since_last_interaction(),
    }
