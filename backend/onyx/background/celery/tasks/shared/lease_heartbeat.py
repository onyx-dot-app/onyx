import contextvars
import threading
from collections.abc import Callable
from types import TracebackType

from onyx.utils.logger import setup_logger

logger = setup_logger()


class LeaseHeartbeat:
    """Renews a Postgres-held lease on a background thread while a job runs.

    `renew` returns False when the job row is no longer ours (e.g. the reaper
    failed it). The heartbeat then stops and sets `lost`; the job must check
    `lost` and stop doing work. An exception from `renew` (e.g. a DB blip) is
    logged and retried on the next interval, since the lease timeout is many
    intervals long.
    """

    def __init__(self, name: str, renew: Callable[[], bool], interval: float):
        self.name = name
        self.lost = threading.Event()
        self._renew = renew
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                if not self._renew():
                    logger.warning("Lease lost: %s", self.name)
                    self.lost.set()
                    return
            except Exception:
                logger.exception("Lease renewal failed: %s", self.name)

    def start(self) -> None:
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
