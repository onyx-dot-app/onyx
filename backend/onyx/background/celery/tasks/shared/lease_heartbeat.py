import contextvars
import threading
import time
from collections.abc import Callable
from types import TracebackType

from onyx.utils.logger import setup_logger

logger = setup_logger()


class LeaseHeartbeat:
    """Renews a Postgres-held lease on a background thread while a job runs.

    `renew` returns False when the job row is no longer ours (e.g. the reaper
    failed it). The heartbeat then stops and sets `lost`. An exception from
    `renew` (e.g. a DB blip) is logged and retried on the next interval.

    The job must stop doing work once `is_lost()` returns True. That is also
    the case when no renewal has succeeded for `max_silence` seconds: the
    reaper may already have failed the job, so `max_silence` must be shorter
    than the reaper's lease timeout.
    """

    def __init__(
        self,
        name: str,
        renew: Callable[[], bool],
        interval: float,
        max_silence: float,
    ):
        self.name = name
        self.lost = threading.Event()
        self._renew = renew
        self._interval = interval
        self._max_silence = max_silence
        self._last_renewed = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                if not self._renew():
                    logger.warning("Lease lost: %s", self.name)
                    self.lost.set()
                    return
                self._last_renewed = time.monotonic()
            except Exception:
                logger.exception("Lease renewal failed: %s", self.name)

    def is_lost(self) -> bool:
        if self.lost.is_set():
            return True
        if time.monotonic() - self._last_renewed > self._max_silence:
            logger.warning("Lease expired without a renewal: %s", self.name)
            self.lost.set()
            return True
        return False

    def start(self) -> None:
        self._last_renewed = time.monotonic()
        # contextvars (e.g. the tenant id) are not inherited by new threads
        context = contextvars.copy_context()
        self._thread = threading.Thread(
            target=context.run, args=(self._loop,), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def __enter__(self) -> "LeaseHeartbeat":
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
