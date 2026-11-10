"""Parallel, sharded listing of a Google Drive domain for a service account.

Every partition (a shared drive, a user's My Drive, the files shared with a
user) lists in one adaptive pool. One task lists one page. A partition with
many pages splits into shards by ``modifiedTime`` range.

**Probe and split.** A shard lists its first page. If there is a next page,
the page shows how dense the range is. When the range holds many pages, the
shard drops that page and splits its range into sub-ranges by query. A shard
that keeps its first page lists to its end. No step depends on the order of
the pages: the ranges are query filters, so shards do not overlap and do not
miss a file. The order only makes the density estimate good.

**Checkpoint.** ``DriveListingState`` holds the open shards. One lock guards
each page step: it emits the page's files, adds the dedup claims, and moves,
splits or closes the shard. A call drains the pool before it ends, so the state
covers exactly the files the call emitted.
"""

import math
import queue
import threading
import time
from collections.abc import Callable, Collection, Generator
from concurrent.futures import Future
from concurrent.futures import wait as wait_for_futures
from datetime import datetime, timezone

from onyx.connectors.google_drive.constants import DRIVE_FOLDER_TYPE
from onyx.connectors.google_drive.file_retrieval import (
    RESOLVED_FROM_SHORTCUT_KEY,
    DriveFileFieldType,
    _get_fields_for_file_type,
    _resolve_file_or_shortcut,
    owner_email,
)
from onyx.connectors.google_drive.models import (
    DriveListingState,
    DriveRetrievalStage,
    GDriveMimeType,
    GoogleDriveCheckpoint,
    GoogleDriveFileType,
    ListingPartition,
    ListingPartitionKind,
    ListingShard,
    RetrievedDriveFile,
)
from onyx.connectors.google_drive.source_operations import (
    DriveCorpus,
    GoogleDriveHttpError,
    GoogleDriveRefreshError,
    GoogleDriveSourceOperations,
)
from onyx.connectors.google_utils.google_utils import GoogleFields
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import DocumentTypeLabel
from onyx.file_processing.file_types import OnyxMimeTypes
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder
from onyx.utils.threadpool_concurrency import (
    ADAPTIVE_INITIAL_WORKERS,
    ADAPTIVE_MAX_WORKERS,
    PUSHBACK_OBSERVER,
    AdaptiveConcurrency,
    AdaptiveTask,
    AdaptiveTaskPool,
    PushbackObserver,
    record_pushback,
    start_thread_future,
)

logger = setup_logger()

# The largest page files.list serves.
LISTING_PAGE_SIZE = 1000
# Pages a shard should hold after a split. A shard's last page is seldom
# full, so small shards add calls. 24 keeps that cost near 2%.
LEAF_TARGET_PAGES = 24
# A split drops one page. Split only when the range should hold this many
# pages, so the dropped page costs little.
MIN_PAGES_TO_SPLIT = 2 * LEAF_TARGET_PAGES
# A partition reads its page of newest files, one more call, only when its
# first page shows it could hold this many pages.
MIN_PAGES_TO_PROBE = LEAF_TARGET_PAGES
# Most sub-ranges one split makes.
SPLIT_MAX_WAYS = 64
# Drive keeps modifiedTime to the millisecond. A range this narrow lists
# serially.
MIN_SHARD_MS = 1000
# Do not split past this many open shards. It bounds the checkpoint.
MAX_OPEN_SHARDS = 2 * ADAPTIVE_MAX_WORKERS
# One call lists for about this long, or this many files, and then drains.
CALL_BUDGET_SECONDS = 60.0
CALL_BUDGET_FILES = 50_000
# How long the consumer waits for a file before it checks the budget.
_OUTPUT_POLL_SECONDS = 0.1

_FILES_QUERY = f"mimeType != '{DRIVE_FOLDER_TYPE}' and trashed = false"
_NEWEST_FIELDS = f"nextPageToken, files({GoogleFields.MODIFIED_TIME.value})"

_GOOGLE_APPS_PREFIX = "application/vnd.google-apps."
_DOCUMENT_MIME_TYPES = {
    GDriveMimeType.DOC.value,
    GDriveMimeType.WORD_DOC.value,
    "application/msword",
}
_SPREADSHEET_MIME_TYPES = {
    GDriveMimeType.SPREADSHEET.value,
    GDriveMimeType.SPREADSHEET_OPEN_FORMAT.value,
    GDriveMimeType.SPREADSHEET_MS_EXCEL.value,
} | OnyxMimeTypes.TABULAR_MIME_TYPES
_PRESENTATION_MIME_TYPES = {
    GDriveMimeType.PPT.value,
    GDriveMimeType.POWERPOINT.value,
    "application/vnd.ms-powerpoint",
}


def _is_transient(error: BaseException) -> bool:
    return isinstance(error, GoogleDriveHttpError) and error.transient


# Google's per-minute quotas refill within a minute. These waits add up to
# about a minute.
_retry_transient = retry_builder(
    tries=7,
    delay=1,
    max_delay=32,
    exceptions=GoogleDriveHttpError,
    retry_if=_is_transient,
)


def drive_document_type(mime_type: str) -> DocumentTypeLabel:
    """The shared label a Drive file counts under. A native Google file
    counts with its Office counterpart. Other Google apps are other files."""
    if mime_type in _DOCUMENT_MIME_TYPES:
        return DocumentTypeLabel.DOCUMENT
    if mime_type in _SPREADSHEET_MIME_TYPES:
        return DocumentTypeLabel.SPREADSHEET
    if mime_type in _PRESENTATION_MIME_TYPES:
        return DocumentTypeLabel.PRESENTATION
    if mime_type == GDriveMimeType.PDF.value:
        return DocumentTypeLabel.PDF
    if mime_type.startswith(_GOOGLE_APPS_PREFIX):
        return DocumentTypeLabel.OTHER
    if mime_type in OnyxMimeTypes.TEXT_MIME_TYPES or mime_type.startswith("text/"):
        return DocumentTypeLabel.TEXT
    if mime_type.startswith("image/"):
        return DocumentTypeLabel.IMAGE
    return DocumentTypeLabel.OTHER


def window_ms(
    start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
) -> tuple[int, int]:
    """[t0, t1) in milliseconds for the window that includes ``end``."""
    return math.floor(start * 1000), math.floor(end * 1000) + 1


def _iso(ms: int) -> str:
    stamp = datetime.fromtimestamp(ms // 1000, tz=timezone.utc)
    return stamp.replace(microsecond=ms % 1000 * 1000).isoformat(
        timespec="milliseconds"
    )


def _modified_ms(file: GoogleDriveFileType) -> int | None:
    raw = file.get(GoogleFields.MODIFIED_TIME.value)
    if not isinstance(raw, str):
        return None
    try:
        return round(datetime.fromisoformat(raw).timestamp() * 1000)
    except ValueError:
        return None


def _expected_pages(
    shard: ListingShard,
    page_times: list[int],
    newest_ms: int,
    newest_page_span_ms: int | None,
) -> tuple[float, int, int]:
    """How many pages the shard's range should hold, with the bounds of the
    part of the range that has files.

    ``page_times`` are the modified times on the shard's first page. With
    ordered pages they are the oldest files of the range, so their span gives
    the density at the old end. ``newest_page_span_ms`` is the span of the
    page of newest files, when it was read."""
    page_min = max(min(page_times), shard.t0)
    page_max = min(max(page_times), shard.t1 - 1)
    data_end = min(max(newest_ms, page_max) + 1, shard.t1)
    pages_per_ms = 1 / max(page_max - page_min, 1)
    if newest_page_span_ms is not None:
        pages_per_ms = (pages_per_ms + 1 / max(newest_page_span_ms, 1)) / 2
    return (data_end - page_min) * pages_per_ms, page_min, data_end


def plan_split(
    shard: ListingShard,
    page_times: list[int],
    newest_ms: int,
    newest_page_span_ms: int | None = None,
) -> list[tuple[int, int]]:
    """The sub-ranges to split ``shard`` into after its first page, or an
    empty list when the shard should keep the page and list on.

    The cuts spread over the part of the range that has files, from the
    page's oldest file to ``newest_ms``. The first and last sub-ranges reach
    the shard's own bounds, so the sub-ranges cover the whole shard. A
    sub-range that holds many pages splits again when it lists its own first
    page."""
    if len(page_times) < 2:
        return []
    expected_pages, page_min, data_end = _expected_pages(
        shard, page_times, newest_ms, newest_page_span_ms
    )
    data_width = data_end - page_min
    if expected_pages < MIN_PAGES_TO_SPLIT:
        return []
    ways = min(
        SPLIT_MAX_WAYS,
        math.ceil(expected_pages / LEAF_TARGET_PAGES),
        data_width // MIN_SHARD_MS,
    )
    if ways < 2:
        return []
    width = data_width // ways
    bounds = [shard.t0]
    bounds.extend(page_min + width * i for i in range(1, ways))
    bounds.append(shard.t1)
    return [(t0, t1) for t0, t1 in zip(bounds, bounds[1:], strict=False) if t0 < t1]


class ParallelDriveLister:
    """Runs one call of the listing: lists until the budget is spent or the
    listing is complete, and updates ``checkpoint.listing`` to match what it
    emitted. The connector supplies the steps that need its settings."""

    def __init__(
        self,
        *,
        ops: GoogleDriveSourceOperations,
        checkpoint: GoogleDriveCheckpoint,
        field_type: DriveFileFieldType,
        requested_shared_drive_ids: Collection[str],
        # Picks who lists a drive, and says if the listing is complete. Users
        # in the collection already list another drive.
        choose_drive_principal: Callable[
            [str, Collection[str]], tuple[str | None, bool]
        ],
        # Checks that a user can call Drive. Returns the failures to report.
        check_impersonation: Callable[[str], tuple[bool, list[RetrievedDriveFile]]],
        # Records a failed impersonation. Returns the failures to report.
        impersonation_failed: Callable[
            [str, GoogleDriveRefreshError], list[RetrievedDriveFile]
        ],
        # Whether to emit a file, and the dedup claim. Called under the lock.
        admit_file: Callable[[GoogleDriveFileType, bool], bool],
    ) -> None:
        if checkpoint.listing is None:
            raise ValueError("The checkpoint has no listing state")
        self._ops = ops
        self._checkpoint = checkpoint
        self._state: DriveListingState = checkpoint.listing
        self._field_type = field_type
        self._fields = _get_fields_for_file_type(field_type)
        self._requested_shared_drive_ids = requested_shared_drive_ids
        self._choose_drive_principal = choose_drive_principal
        self._check_impersonation = check_impersonation
        self._impersonation_failed = impersonation_failed
        self._admit_file = admit_file

        # Guards the state, the checkpoint fields this class writes, and the
        # fields below.
        self._lock = threading.Lock()
        self._output: queue.SimpleQueue[RetrievedDriveFile] = queue.SimpleQueue()
        self._emitted = 0
        # Partitions that a task is planning now.
        self._planning: set[ListingPartition] = set()
        self._observer = PushbackObserver()
        self._pool = AdaptiveTaskPool(
            AdaptiveConcurrency(
                self._observer,
                initial=self._state.concurrency_limit or ADAPTIVE_INITIAL_WORKERS,
            )
        )

    # --- The call -----------------------------------------------------------

    def run(self) -> Generator[RetrievedDriveFile, None, None]:
        with self._lock:
            for shard_id in sorted(self._state.shards):
                self._pool.add(self._page_task(shard_id))
            for task in self._plan_tasks():
                self._pool.add(task)

        pool_run: Future[None] = start_thread_future(self._run_pool, name="drive-list")
        deadline = time.monotonic() + CALL_BUDGET_SECONDS
        try:
            while not pool_run.done():
                if time.monotonic() >= deadline:
                    self._pool.drain()
                try:
                    yield self._output.get(timeout=_OUTPUT_POLL_SECONDS)
                except queue.Empty:
                    continue
            while not self._output.empty():
                yield self._output.get_nowait()
        finally:
            # Also runs when the consumer stops early: wait for the pages in
            # flight, so no thread writes the checkpoint after this returns.
            self._pool.drain()
            wait_for_futures([pool_run])
            self._state.concurrency_limit = self._pool.limit
        pool_run.result()

    def _run_pool(self) -> None:
        # Set here, so the pool's worker threads inherit it.
        token = PUSHBACK_OBSERVER.set(self._observer)
        try:
            self._pool.run()
        finally:
            PUSHBACK_OBSERVER.reset(token)

    def _emit(self, files: list[RetrievedDriveFile]) -> None:
        """The caller holds the lock."""
        for file in files:
            self._output.put(file)
        self._emitted += len(files)
        if self._emitted >= CALL_BUDGET_FILES:
            self._pool.drain()

    # --- Planning a partition -------------------------------------------------

    def _plan_tasks(self) -> list[AdaptiveTask]:
        """Tasks for the pending partitions that can start. A shared-with-user
        partition waits until every exact partition has begun: most owners are
        then listed, and their files are dropped, not put in the dedup set.
        The caller holds the lock."""
        exact_pending = any(
            partition.kind is not ListingPartitionKind.SHARED_WITH_USER
            for partition in self._state.pending_partitions
        )
        tasks: list[AdaptiveTask] = []
        for partition in self._state.pending_partitions:
            if partition in self._planning:
                continue
            if (
                partition.kind is ListingPartitionKind.SHARED_WITH_USER
                and exact_pending
            ):
                continue
            self._planning.add(partition)
            tasks.append(self._plan_task(partition))
        return tasks

    def _plan_task(self, partition: ListingPartition) -> AdaptiveTask:
        def run() -> list[AdaptiveTask]:
            if partition.kind is ListingPartitionKind.SHARED_DRIVE:
                shard_id = self._plan_shared_drive(partition)
            else:
                shard_id = self._plan_user_partition(partition)
            with self._lock:
                tasks = self._plan_tasks()
            if shard_id is not None:
                tasks.append(self._page_task(shard_id))
            return tasks

        return run

    def _plan_shared_drive(self, partition: ListingPartition) -> int | None:
        drive_id = partition.key
        with self._lock:
            busy = {shard.principal for shard in self._state.shards.values()}
        email, complete = self._choose_drive_principal(drive_id, busy)
        with self._lock:
            checkpoint = self._checkpoint
            checkpoint.incomplete_drive_ids.discard(drive_id)
            if email is None:
                self._finish_planning(partition)
                checkpoint.incomplete_drive_ids.add(drive_id)
                if drive_id in self._requested_shared_drive_ids:
                    checkpoint.unreachable_target_ids.add(drive_id)
                return None
            checkpoint.organizer_email_by_drive_id[drive_id] = email
            if complete:
                # Only an organizer's listing is a complete record of the drive.
                self._state.listed_drive_ids.add(drive_id)
            else:
                checkpoint.incomplete_drive_ids.add(drive_id)
            logger.info("Listing shared drive %s as %s", drive_id, email)
            return self._start_partition(partition, email, exact=complete)

    def _plan_user_partition(self, partition: ListingPartition) -> int | None:
        email = partition.key
        shared_with = partition.kind is ListingPartitionKind.SHARED_WITH_USER
        with self._lock:
            failed = email in self._checkpoint.failed_impersonation_emails
            # The My Drive partition already checked this user.
            checked = email.lower() in self._state.listed_owners
        usable = not failed
        failures: list[RetrievedDriveFile] = []
        if usable and not checked:
            usable, failures = self._check_impersonation(email)
        with self._lock:
            self._emit(failures)
            if not usable:
                self._finish_planning(partition)
                return None
            if not shared_with:
                self._state.listed_owners.add(email.lower())
            return self._start_partition(partition, email, exact=not shared_with)

    def _finish_planning(self, partition: ListingPartition) -> None:
        """The caller holds the lock."""
        self._state.pending_partitions.remove(partition)
        self._planning.discard(partition)

    def _start_partition(
        self, partition: ListingPartition, principal: str, exact: bool
    ) -> int:
        """Moves a partition from pending to its first shard, which covers the
        whole window. The caller holds the lock."""
        self._finish_planning(partition)
        self._state.started_partitions.append((partition, principal, exact))
        return self._add_shard(
            partition,
            principal,
            exact,
            self._state.window_t0,
            self._state.window_t1,
            newest_ms=None,
        )

    def _add_shard(
        self,
        partition: ListingPartition,
        principal: str,
        exact: bool,
        t0: int,
        t1: int,
        newest_ms: int | None,
    ) -> int:
        """The caller holds the lock."""
        state = self._state
        shard_id = state.next_shard_id
        state.next_shard_id += 1
        state.shards[shard_id] = ListingShard(
            id=shard_id,
            partition=partition,
            principal=principal,
            t0=t0,
            t1=t1,
            newest_ms=newest_ms,
            exact=exact,
        )
        return shard_id

    # --- Listing a page ---------------------------------------------------------

    def _page_task(self, shard_id: int) -> AdaptiveTask:
        def run() -> list[AdaptiveTask]:
            with self._lock:
                shard = self._state.shards.get(shard_id)
            if shard is None:
                return []
            try:
                return self._list_one_page(shard.model_copy())
            except GoogleDriveRefreshError as error:
                return self._partition_failed(shard, error)

        return run

    def _list_one_page(self, shard: ListingShard) -> list[AdaptiveTask]:
        files, next_token = self._fetch_page(shard)

        if next_token is not None and shard.can_split:
            children = self._try_split(shard, files)
            if children is not None:
                return [self._page_task(child_id) for child_id in children]

        # A shortcut costs one files.get, so resolve outside the lock.
        resolved: list[GoogleDriveFileType] = []
        for file in files:
            target = self._resolve_shortcut(shard.principal, file)
            if target is not None:
                resolved.append(target)

        with self._lock:
            live = self._state.shards.get(shard.id)
            if live is None:
                # The partition failed while this page was in flight.
                return []
            self._emit(
                [
                    self._retrieved(shard, file)
                    for file in resolved
                    if self._admit(shard, file)
                ]
            )
            if next_token is None:
                del self._state.shards[shard.id]
                return []
            live.page_token = next_token
            live.can_split = False
        return [self._page_task(shard.id)]

    def _resolve_shortcut(
        self, user_email: str, file: GoogleDriveFileType
    ) -> GoogleDriveFileType | None:
        """The file, or the target of a shortcut. files.get has no retry of
        its own, and one failed read must not fail the whole call."""

        def resolve() -> GoogleDriveFileType | None:
            try:
                return _resolve_file_or_shortcut(
                    self._ops, user_email, file, self._field_type
                )
            except GoogleDriveHttpError as error:
                if error.transient:
                    record_pushback()
                raise

        return _retry_transient(resolve)()

    def _fetch_page(
        self, shard: ListingShard
    ) -> tuple[list[GoogleDriveFileType], str | None]:
        files: list[GoogleDriveFileType] = []
        next_token: str | None = None
        for item in self._ops.list_files(
            variant=self._variant(shard),
            user_email=shard.principal,
            fields=self._fields,
            query=self._query(shard, shard.t0, shard.t1),
            drive_id=self._drive_id(shard),
            order_by=GoogleFields.MODIFIED_TIME.value,
            page_token=shard.page_token,
            page_size=LISTING_PAGE_SIZE,
            max_num_pages=1,
            continue_on_404_or_403=True,
        ):
            if isinstance(item, str):
                next_token = item
            else:
                files.append(item)
        return files, next_token

    @staticmethod
    def _variant(shard: ListingShard) -> DriveCorpus:
        if shard.partition.kind is ListingPartitionKind.SHARED_DRIVE:
            return DriveCorpus.DRIVE
        return DriveCorpus.USER

    @staticmethod
    def _drive_id(shard: ListingShard) -> str | None:
        if shard.partition.kind is ListingPartitionKind.SHARED_DRIVE:
            return shard.partition.key
        return None

    @staticmethod
    def _query(shard: ListingShard, t0: int, t1: int) -> str:
        query = _FILES_QUERY
        if shard.partition.kind is ListingPartitionKind.MY_DRIVE:
            query += " and 'me' in owners"
        field = GoogleFields.MODIFIED_TIME.value
        return f"{query} and {field} >= '{_iso(t0)}' and {field} < '{_iso(t1)}'"

    def _retrieved(
        self, shard: ListingShard, file: GoogleDriveFileType
    ) -> RetrievedDriveFile:
        if shard.partition.kind is ListingPartitionKind.SHARED_DRIVE:
            return RetrievedDriveFile(
                completion_stage=DriveRetrievalStage.SHARED_DRIVE_FILES,
                drive_file=file,
                user_email=shard.principal,
                parent_id=shard.partition.key,
            )
        return RetrievedDriveFile(
            completion_stage=DriveRetrievalStage.MY_DRIVE_FILES,
            drive_file=file,
            user_email=shard.principal,
        )

    def _admit(self, shard: ListingShard, file: GoogleDriveFileType) -> bool:
        """Whether this shard emits the file. A file that a listing which has
        begun covers is dropped. A file with no exact partition is claimed in
        the dedup set. The caller holds the lock, so no listing begins between
        the coverage check and the claim."""
        state = self._state
        kind = shard.partition.kind
        via_shortcut = RESOLVED_FROM_SHORTCUT_KEY in file
        file_drive_id = file.get("driveId")
        owner = owner_email(file)

        if kind is ListingPartitionKind.SHARED_WITH_USER:
            if file_drive_id in state.listed_drive_ids or owner in state.listed_owners:
                return False
            return self._admit_file(file, False)

        if kind is ListingPartitionKind.SHARED_DRIVE:
            own = file_drive_id == shard.partition.key
            covered_elsewhere = not own and file_drive_id in state.listed_drive_ids
        else:
            own = owner == shard.partition.key.lower() and not file_drive_id
            covered_elsewhere = not own and (
                file_drive_id in state.listed_drive_ids or owner in state.listed_owners
            )
        # A shortcut to a file of this partition: the listing has the file.
        if via_shortcut and own:
            return False
        exact = shard.exact and own and not via_shortcut
        if not exact and covered_elsewhere:
            return False
        return self._admit_file(file, exact)

    # --- Splitting ------------------------------------------------------------

    def _try_split(
        self, shard: ListingShard, files: list[GoogleDriveFileType]
    ) -> list[int] | None:
        """Splits the shard when its range should hold many pages. Returns the
        new shard ids, or None when the shard keeps its page."""
        if shard.t1 - shard.t0 < 2 * MIN_SHARD_MS:
            return None
        with self._lock:
            if len(self._state.shards) >= MAX_OPEN_SHARDS:
                return None
        page_times = [ms for file in files if (ms := _modified_ms(file)) is not None]
        if len(page_times) < 2:
            return None
        newest_ms = shard.newest_ms
        newest_page_span_ms: int | None = None
        if newest_ms is None:
            # The first shard of a partition. The window end stands in for
            # the newest file, which overstates the range.
            could_hold, _, _ = _expected_pages(shard, page_times, shard.t1 - 1, None)
            if could_hold < MIN_PAGES_TO_PROBE:
                return None
            newest_ms, newest_page_span_ms = self._read_newest_page(shard)
        ranges = plan_split(shard, page_times, newest_ms, newest_page_span_ms)
        if not ranges:
            return None
        with self._lock:
            state = self._state
            if shard.id not in state.shards:
                return []
            if len(state.shards) + len(ranges) - 1 > MAX_OPEN_SHARDS:
                return None
            del state.shards[shard.id]
            children = [
                self._add_shard(
                    shard.partition, shard.principal, shard.exact, t0, t1, newest_ms
                )
                for t0, t1 in ranges
            ]
        logger.debug(
            "Split %s %s [%s, %s) into %s shards",
            shard.partition.kind.value,
            shard.partition.key,
            _iso(shard.t0),
            _iso(shard.t1),
            len(children),
        )
        return children

    def _read_newest_page(self, shard: ListingShard) -> tuple[int, int | None]:
        """The modifiedTime of the newest file in the shard's range, and the
        time span of the page of newest files (None when the page is not
        full). They only steer a split, so a wrong answer loses no file. A
        list call costs the same at any page size."""
        times: list[int] = []
        full_page = False
        for item in self._ops.list_files(
            variant=self._variant(shard),
            user_email=shard.principal,
            fields=_NEWEST_FIELDS,
            query=self._query(shard, shard.t0, shard.t1),
            drive_id=self._drive_id(shard),
            order_by=f"{GoogleFields.MODIFIED_TIME.value} desc",
            page_size=LISTING_PAGE_SIZE,
            max_num_pages=1,
            continue_on_404_or_403=True,
        ):
            if isinstance(item, str):
                full_page = True
            elif (modified := _modified_ms(item)) is not None:
                times.append(modified)
        if not times:
            return shard.t1 - 1, None
        span = max(times) - min(times) if full_page and len(times) > 1 else None
        return max(times), span

    # --- Failure --------------------------------------------------------------

    def _partition_failed(
        self, shard: ListingShard, error: GoogleDriveRefreshError
    ) -> list[AdaptiveTask]:
        """The service account can no longer act as the shard's user. Closes
        every shard of the partition. A shared drive goes back to pending, to
        list again from its start as another member."""
        failures = self._impersonation_failed(shard.principal, error)
        partition = shard.partition
        with self._lock:
            state = self._state
            if shard.id not in state.shards:
                # Another shard of the partition reported the failure.
                return []
            for shard_id in [
                shard_id
                for shard_id, open_shard in state.shards.items()
                if open_shard.partition == partition
            ]:
                del state.shards[shard_id]
            state.started_partitions = [
                started
                for started in state.started_partitions
                if started[0] != partition
            ]
            self._emit(failures)
            if partition.kind is ListingPartitionKind.SHARED_DRIVE:
                state.listed_drive_ids.discard(partition.key)
                self._checkpoint.organizer_email_by_drive_id.pop(partition.key, None)
                state.pending_partitions.insert(0, partition)
            elif partition.kind is ListingPartitionKind.MY_DRIVE:
                # Files of this owner are no longer covered, so a shared-with
                # listing that starts later keeps them.
                state.listed_owners.discard(partition.key.lower())
            return self._plan_tasks()


def extend_window(state: DriveListingState, t1: int) -> None:
    """Moves the end of the window to ``t1`` when a resumed listing gets a
    later end. Each partition that began gets a shard for the added range.
    Pending partitions use the new end when they start."""
    if t1 <= state.window_t1:
        return
    for partition, principal, exact in state.started_partitions:
        shard_id = state.next_shard_id
        state.next_shard_id += 1
        state.shards[shard_id] = ListingShard(
            id=shard_id,
            partition=partition,
            principal=principal,
            t0=state.window_t1,
            t1=t1,
            exact=exact,
        )
    state.window_t1 = t1
