from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run_shutdown_routine() -> None:
    """Runs during FastAPI lifespan shutdown (SIGTERM from kubelet, idle timeout, etc.).

    PR 2: stub. Logs the call and returns.
    PR 5: triggers a snapshot to S3 and waits for completion before returning.
    """
    logger.info("Shutdown routine invoked (PR 2 stub — snapshot logic lands in PR 5)")
