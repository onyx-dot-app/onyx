import tracemalloc

from onyx.utils.logger import setup_logger

logger = setup_logger()

DANSWER_TRACEMALLOC_FRAMES = 10


class OnyxTracer:
    def __init__(self) -> None:
        self.snapshot_first: tracemalloc.Snapshot | None = None
        self.snapshot_prev: tracemalloc.Snapshot | None = None
        self.snapshot: tracemalloc.Snapshot | None = None

    def start(self) -> None:
        tracemalloc.start(DANSWER_TRACEMALLOC_FRAMES)

    def stop(self) -> None:
        tracemalloc.stop()

    def snap(self) -> None:
        snapshot = tracemalloc.take_snapshot()
        # Filter out irrelevant frames (e.g., from tracemalloc itself or importlib)
        snapshot = snapshot.filter_traces(
            (
                tracemalloc.Filter(False, tracemalloc.__file__),  # Exclude tracemalloc
                tracemalloc.Filter(
                    False, "<frozen importlib._bootstrap>"
                ),  # Exclude importlib
                tracemalloc.Filter(
                    False, "<frozen importlib._bootstrap_external>"
                ),  # Exclude external importlib
            )
        )

        if not self.snapshot_first:
            self.snapshot_first = snapshot

        if self.snapshot:
            self.snapshot_prev = self.snapshot

        self.snapshot = snapshot

    def log_snapshot(self, numEntries: int) -> None:
        if not self.snapshot:
            return

        stats = self.snapshot.statistics("traceback")
        for s in stats[:numEntries]:
            logger.debug(f"Tracer snap: {s}")
            for line in s.traceback:
                logger.debug(f"* {line}")

    @staticmethod
    def log_diff(
        snap_current: tracemalloc.Snapshot,
        snap_previous: tracemalloc.Snapshot,
        numEntries: int,
    ) -> None:
        stats = snap_current.compare_to(snap_previous, "traceback")
        for s in stats[:numEntries]:
            logger.debug(f"Tracer diff: {s}")
            for line in s.traceback.format():
                logger.debug(f"* {line}")

    def log_previous_diff(self, numEntries: int) -> None:
        if not self.snapshot or not self.snapshot_prev:
            return

        OnyxTracer.log_diff(self.snapshot, self.snapshot_prev, numEntries)

    def log_first_diff(self, numEntries: int) -> None:
        if not self.snapshot or not self.snapshot_first:
            return

        OnyxTracer.log_diff(self.snapshot, self.snapshot_first, numEntries)
