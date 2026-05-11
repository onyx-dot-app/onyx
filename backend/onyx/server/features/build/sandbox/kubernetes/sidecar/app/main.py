from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, Response

from app.config import get_settings
from app.idle import IdleTracker, cancel_idle_task, idle_middleware_factory
from app.lifecycle import run_shutdown_routine
from app.routers import exec as exec_router
from app.routers import files, health, snapshot

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()

    # Validate auth configuration up-front so we fail fast if misconfigured.
    settings.load_auth_token()

    tracker = IdleTracker(
        idle_timeout_seconds=settings.idle_timeout_seconds,
        check_interval_seconds=settings.idle_check_interval_seconds,
    )
    app.state.idle = tracker

    idle_task = asyncio.create_task(tracker.run())
    logger.info(
        "Sidecar started on %s:%d (workspace=%s, idle_timeout=%ds)",
        settings.host,
        settings.port,
        settings.workspace_root,
        settings.idle_timeout_seconds,
    )

    try:
        yield
    finally:
        # SIGTERM from kubelet (or idle-triggered self-kill) lands here.
        logger.info("Sidecar shutting down")
        await cancel_idle_task(idle_task)
        await run_shutdown_routine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Craft Sandbox Sidecar",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Idle-tracking middleware must wrap all routes so authenticated activity bumps the timer.
    # The IdleTracker is constructed in lifespan, so we look it up off app.state at request time.
    @app.middleware("http")
    async def _idle_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        tracker: IdleTracker | None = getattr(request.app.state, "idle", None)
        if tracker is None:
            return await call_next(request)
        return await idle_middleware_factory(tracker)(request, call_next)

    app.include_router(health.router)
    app.include_router(files.router)
    app.include_router(exec_router.router)
    app.include_router(snapshot.router)

    return app


app = create_app()


def run() -> None:
    """Entrypoint registered as `sandbox-sidecar` in pyproject.toml."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
