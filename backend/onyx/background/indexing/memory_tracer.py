import tracemalloc

from onyx.utils.logger import setup_logger

logger = setup_logger()

DANSWER_TRACEMALLOC_FRAMES = 10


class MemoryTracer:
    def __init__(self, interval: int = 0, num_print_entries: int = 5):
        self.interval = interval
        self.num_print_entries = num_print_entries
        self.snapshot_first: tracemalloc.Snapshot | None = None
        self.snapshot_prev: tracemalloc.Snapshot | None = None
        self.snapshot: tracemalloc.Snapshot | None = None
        self.counter = 0

    def start(self) -> None:
        """Start the memory tracer if interval is greater than 0."""
        if self.interval > 0:
            logger.debug("Memory tracer starting: interval=%s", self.interval)
            tracemalloc.start(DANSWER_TRACEMALLOC_FRAMES)
            self._take_snapshot()

    def stop(self) -> None:
        """Stop the memory tracer if it's running."""
        if self.interval > 0:
            self.log_final_diff()
            tracemalloc.stop()
            logger.debug("Memory tracer stopped.")

    def _take_snapshot(self) -> None:
        """Take a snapshot and update internal snapshot states."""
        snapshot = tracemalloc.take_snapshot()
        # Filter out irrelevant frames
        snapshot = snapshot.filter_traces(
            (
                tracemalloc.Filter(False, tracemalloc.__file__),
                tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
                tracemalloc.Filter(False, "<frozen importlib._bootstrap_external>"),
            )
        )

        if not self.snapshot_first:
            self.snapshot_first = snapshot

        if self.snapshot:
            self.snapshot_prev = self.snapshot

        self.snapshot = snapshot

    def _log_diff(
        self, current: tracemalloc.Snapshot, previous: tracemalloc.Snapshot
    ) -> None:
        """Log the memory difference between two snapshots."""
        stats = current.compare_to(previous, "traceback")
        for s in stats[: self.num_print_entries]:
            logger.debug("Tracer diff: %s", s)
            for line in s.traceback.format():
                logger.debug("* %s", line)

    def increment_and_maybe_trace(self) -> None:
        """Increment counter and perform trace if interval is hit."""
        if self.interval <= 0:
            return

        self.counter += 1
        if self.counter % self.interval == 0:
            logger.debug(
                "Running trace comparison for batch %s. interval=%s",
                self.counter,
                self.interval,
            )
            self._take_snapshot()
            if self.snapshot and self.snapshot_prev:
                self._log_diff(self.snapshot, self.snapshot_prev)

    def log_final_diff(self) -> None:
        """Log the final memory diff between start and end of indexing."""
        if self.interval <= 0:
            return

        logger.debug(
            "Running trace comparison between start and end of indexing. %s batches processed.",
            self.counter,
        )
        self._take_snapshot()
        if self.snapshot and self.snapshot_first:
            self._log_diff(self.snapshot, self.snapshot_first)
