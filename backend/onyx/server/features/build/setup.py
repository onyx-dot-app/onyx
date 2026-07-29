"""Craft startup work. Callers gate on ENABLE_CRAFT."""

from __future__ import annotations

import threading

from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _prewarm_sandbox() -> None:
    try:
        get_sandbox_manager().prewarm()
    except Exception:
        # An optimisation only: provision() still does the work on demand, and
        # reports failure against the request that caused it.
        logger.warning("Sandbox prewarm failed.", exc_info=True)


def setup_craft() -> threading.Thread:
    """Start Craft's background startup work, returning the thread for joining.

    A thread rather than inline work: SandboxManager.prewarm() blocks, and on a
    mutable tag such as the default `:latest` the Docker backend contacts the
    registry on every startup, not just the first. Running it inline would put
    all of Onyx's readiness behind the registry being reachable. Nothing awaits
    the result, so a daemon thread keeps it off the event loop and out of
    shutdown's way.
    """
    thread = threading.Thread(
        target=_prewarm_sandbox, name="craft-sandbox-prewarm", daemon=True
    )
    thread.start()
    return thread
