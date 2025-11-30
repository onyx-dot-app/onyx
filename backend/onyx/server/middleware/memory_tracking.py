"""Lightweight memory tracking middleware that only logs when memory is high."""

import psutil
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from onyx.utils.logger import setup_logger

logger = setup_logger()

# Only log when memory exceeds these thresholds (MB)
MEMORY_WARNING_THRESHOLD = 2000  # 2GB - log warning
MEMORY_CRITICAL_THRESHOLD = 2500  # 2.5GB - log error
MEMORY_DELTA_THRESHOLD = 200  # Log if single request uses >200MB


class MemoryTrackingMiddleware(BaseHTTPMiddleware):
    """Tracks memory usage for requests, only logging when thresholds are exceeded."""

    async def dispatch(self, request: Request, call_next):
        process = psutil.Process()
        mem_before_mb = process.memory_info().rss / (1024 * 1024)

        # Only check expensive endpoints or when already high
        should_track = mem_before_mb > MEMORY_WARNING_THRESHOLD or any(
            path in request.url.path
            for path in [
                "/send-message",
                "/upload",
                "/indexing",
                "/search",
                "/query",
            ]
        )

        if not should_track:
            return await call_next(request)

        # Track memory for concerning requests
        response = await call_next(request)

        mem_after_mb = process.memory_info().rss / (1024 * 1024)
        mem_delta_mb = mem_after_mb - mem_before_mb

        # Only log if memory is high or spike is large
        if mem_after_mb > MEMORY_CRITICAL_THRESHOLD:
            logger.error(
                f"[MEM CRITICAL] {mem_after_mb:.0f}MB after {request.method} "
                f"{request.url.path} (+{mem_delta_mb:.0f}MB)"
            )
        elif (
            mem_after_mb > MEMORY_WARNING_THRESHOLD
            or mem_delta_mb > MEMORY_DELTA_THRESHOLD
        ):
            logger.warning(
                f"[MEM HIGH] {mem_after_mb:.0f}MB after {request.method} "
                f"{request.url.path} (+{mem_delta_mb:.0f}MB)"
            )

        return response
