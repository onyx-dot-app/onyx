"""Parallel, sharded listing of a Google Drive domain for a service account.

Every partition (a shared drive, a user's My Drive, the files shared with a
user) lists in one adaptive pool. One task lists one page. A partition with
many pages splits into shards by ``modifiedTime`` range.

**Probe and split.** A shard lists a page. If there is a next page, the page
and the pages the shard kept before show how dense the range is. When the
range holds many files, the shard drops that page and splits the rest of its
range into sub-ranges by query. Each page checks again, so a page that makes
the range look sparse does not stop a later split. No step depends on the
order of the pages: the ranges are query filters, so shards do not overlap and
do not miss a file. The order only makes the density estimate good.

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
from enum import Enum

from onyx.connectors.google_drive.constants import DRIVE_FOLDER_TYPE
from onyx.connectors.google_drive.file_retrieval import (
    RESOLVED_FROM_SHORTCUT_KEY,
    TARGET_MODIFIED_TIME_KEY,
    DriveFileFieldType,
    get_fields_for_file_type,
    owner_email,
    resolve_file_or_shortcut,
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
# The split thresholds count files, not pages: Drive serves about 460 lean
# files a page, but only about 100 with permission fields.
# Files a shard should hold after a split. A shard's last page is seldom
# full, so small shards add calls. About 22 lean pages keep that cost near 2%.
LEAF_TARGET_FILES = 10_000
# A split drops one page. Split only when the range should hold this many
# files, so the dropped page costs little.
MIN_FILES_TO_SPLIT = 2 * LEAF_TARGET_FILES
# A partition reads its page of newest files, one more call, only when a
# page shows it could hold this many files.
MIN_FILES_TO_PROBE = LEAF_TARGET_FILES
# Most sub-ranges one split makes.
SPLIT_MAX_WAYS = 64
# Drive keeps modifiedTime to the millisecond. A range this narrow lists
# serially.
MIN_SHARD_MS = 1000
# Do not split past this many open shards. It bounds the checkpoint.
MAX_OPEN_SHARDS = 2 * ADAPTIVE_MAX_WORKERS
# Ids a shard keeps at its newest modifiedTime. Past this, the shard does not
# split on a page that starts at that time. It bounds the checkpoint.
MAX_FRONTIER_IDS = 2000
# One call lists for about this long, or this many files, and then drains.
CALL_BUDGET_SECONDS = 60.0
CALL_BUDGET_FILES = 50_000
# The file budget of one inline call, where the caller converts each file to a
# document in the same call. It caps the documents one call converts. Keep it
# at least LISTING_PAGE_SIZE, or a call cannot take a full page.
INLINE_CALL_BUDGET_FILES = 2 * LISTING_PAGE_SIZE
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
    return _iso_ms(file.get(GoogleFields.MODIFIED_TIME.value))


def _iso_ms(raw: object) -> int | None:
    if not isinstance(raw, str):
        return None
    try:
        return round(datetime.fromisoformat(raw).timestamp() * 1000)
    except ValueError:
        return None


def page_density(times: list[int]) -> float:
    """Files per millisecond over the time span of one page."""
    return len(times) / max(max(times) - min(times), 1)


def history_density(shard: ListingShard) -> float | None:
    """Files per millisecond over the pages the shard kept, or None before
    it kept a page. One page can fall between two bulk uploads and look
    sparse. The pages kept so far cover many uploads."""
    if shard.kept_since_ms is None or shard.frontier_ms is None:
        return None
    return shard.kept_files / max(shard.frontier_ms - shard.kept_since_ms, 1)


def _expected_files(
    shard: ListingShard,
    page_times: list[int],
    newest_ms: int,
    newest_density: float | None,
) -> tuple[float, int, int]:
    """How many files the shard's range should hold, with the bounds of the
    part of the range that has files.

    ``page_times`` are the modified times on the page the shard just read.
    With ordered pages they are the oldest files of the range, so they give
    the density at the old end. ``newest_density`` is the density of the
    page of newest files, when it was read. The estimate takes the larger of
    that and the density of the pages the shard kept."""
    page_min = max(min(page_times), shard.t0)
    page_max = min(max(page_times), shard.t1 - 1)
    data_end = min(max(newest_ms, page_max) + 1, shard.t1)
    files_per_ms = page_density(page_times)
    if newest_density is not None:
        files_per_ms = (files_per_ms + newest_density) / 2
    kept = history_density(shard)
    if kept is not None:
        files_per_ms = max(files_per_ms, kept)
    return (data_end - page_min) * files_per_ms, page_min, data_end


def plan_split(
    shard: ListingShard,
    page_times: list[int],
    newest_ms: int,
    newest_density: float | None = None,
) -> list[tuple[int, int]]:
    """The sub-ranges to split ``shard`` into after a page, or an empty list
    when the shard should keep the page and list on.

    The cuts spread over the part of the range that has files, from the
    page's oldest file to ``newest_ms``. The first and last sub-ranges reach
    the shard's own bounds, so the sub-ranges cover the whole shard. A
    sub-range that holds many pages splits again when it lists its own first
    page."""
    if len(page_times) < 2:
        return []
    expected_files, page_min, data_end = _expected_files(
        shard, page_times, newest_ms, newest_density
    )
    data_width = data_end - page_min
    if expected_files < MIN_FILES_TO_SPLIT:
        return []
    ways = min(
        SPLIT_MAX_WAYS,
        math.ceil(expected_files / LEAF_TARGET_FILES),
        data_width // MIN_SHARD_MS,
    )
    if ways < 2:
        return []
    width = data_width // ways
    bounds = [shard.t0]
    bounds.extend(page_min + width * i for i in range(1, ways))
    bounds.append(shard.t1)
    return [(t0, t1) for t0, t1 in zip(bounds, bounds[1:], strict=False) if t0 < t1]


def _move_frontier(shard: ListingShard, files: list[GoogleDriveFileType]) -> None:
    """Records the page that the shard kept: the newest modifiedTime so far
    and the ids at that time. A later page needs them to split."""
    listed = [
        (ms, file_id)
        for file in files
        if (ms := _modified_ms(file)) is not None
        and isinstance(file_id := file.get("id"), str)
    ]
    if not listed or not shard.in_order:
        return
    page_min = min(ms for ms, _ in listed)
    page_max = max(ms for ms, _ in listed)
    if shard.frontier_ms is not None and page_min < shard.frontier_ms:
        # Drive did not keep the order of the pages.
        shard.in_order = False
        shard.frontier_ids = []
        return
    if shard.kept_since_ms is None:
        shard.kept_since_ms = page_min
    shard.kept_files += len(listed)
    if shard.frontier_ms is None or page_max > shard.frontier_ms:
        shard.frontier_ms = page_max
        shard.frontier_ids = []
        shard.frontier_overflow = False
    if shard.frontier_overflow:
        return
    shard.frontier_ids.extend(
        file_id for ms, file_id in listed if ms == shard.frontier_ms
    )
    if len(shard.frontier_ids) > MAX_FRONTIER_IDS:
        # A bulk upload can give thousands of files one modifiedTime.
        shard.frontier_overflow = True
        shard.frontier_ids = []


class _SplitRefusal(Enum):
    """Why a shard keeps its page instead of splitting."""

    # The range holds too few files to split. A later page checks again.
    DENSITY = "density"
    # The pages came out of modifiedTime order. The shard lists to its end.
    OUT_OF_ORDER = "out_of_order"
    # The open shard cap leaves no room. A later page can try again.
    SHARD_CAP = "shard_cap"
    # The page starts at a time that more files share than the shard keeps
    # ids for. A later page that starts after that time can split.
    FRONTIER_OVERFLOW = "frontier_overflow"
    # The shard has no upper bound to split at.
    OPEN_END = "open_end"


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
        # Records that Drive denied a page of a partition (403 or 404).
        # Returns the failures to report.
        listing_denied: Callable[
            [ListingPartition, str, GoogleDriveHttpError], list[RetrievedDriveFile]
        ],
        # Whether to emit a file, and the dedup claim. Called under the lock.
        admit_file: Callable[[GoogleDriveFileType, bool], bool],
        # The caller converts each file before it reads the next. One page is
        # in flight, and the call stops before a page could pass
        # INLINE_CALL_BUDGET_FILES, so the files that wait for conversion
        # stay few.
        inline: bool = False,
    ) -> None:
        if checkpoint.listing is None:
            raise ValueError("The checkpoint has no listing state")
        self._ops = ops
        self._checkpoint = checkpoint
        self._state: DriveListingState = checkpoint.listing
        self._field_type = field_type
        self._fields = get_fields_for_file_type(field_type)
        self._requested_shared_drive_ids = requested_shared_drive_ids
        self._choose_drive_principal = choose_drive_principal
        self._check_impersonation = check_impersonation
        self._impersonation_failed = impersonation_failed
        self._listing_denied = listing_denied
        self._admit_file = admit_file
        self._inline = inline
        self._budget_files = INLINE_CALL_BUDGET_FILES if inline else CALL_BUDGET_FILES

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
                maximum=1 if inline else ADAPTIVE_MAX_WORKERS,
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
            if not self._inline:
                # The limit of one worker says nothing of what Drive allows.
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
        if self._inline:
            # The one page in flight is the one that emits here, so the call
            # stops before the next page could pass the budget.
            spent = self._emitted > 0 and (
                self._emitted + LISTING_PAGE_SIZE > self._budget_files
            )
        else:
            spent = self._emitted >= self._budget_files
        if spent:
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
        skip_ids: list[str] | None = None,
        owner_filter: str | None = None,
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
            skip_ids=skip_ids or [],
            owner_filter=owner_filter,
            open_end=state.open_end and t1 >= state.window_t1,
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
                failures = self._impersonation_failed(shard.principal, error)
                return self._partition_failed(shard, failures, list_again=True)
            except GoogleDriveHttpError as error:
                if not error.access_denied:
                    raise
                # An empty page would read as deleted files, and the partition
                # would count as listed. Report the partition as failed.
                failures = self._listing_denied(shard.partition, shard.principal, error)
                return self._partition_failed(shard, failures, list_again=False)

        return run

    def _list_one_page(self, shard: ListingShard) -> list[AdaptiveTask]:
        files, next_token = self._fetch_page(shard)

        if next_token is not None:
            children = self._try_split(shard, files)
            if isinstance(children, list):
                return [self._page_task(child_id) for child_id in children]

        if shard.skip_ids:
            # The shard this range came from already listed these files.
            skip = set(shard.skip_ids)
            files = [file for file in files if file.get("id") not in skip]

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
            _move_frontier(live, files)
        return [self._page_task(shard.id)]

    def _resolve_shortcut(
        self, user_email: str, file: GoogleDriveFileType
    ) -> GoogleDriveFileType | None:
        """The file, or the target of a shortcut. files.get has no retry of
        its own, and one failed read must not fail the whole call."""

        def resolve() -> GoogleDriveFileType | None:
            try:
                return resolve_file_or_shortcut(
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
        elif shard.partition.kind is ListingPartitionKind.SHARED_WITH_USER:
            # The user's My Drive partition lists the user's own files.
            query += " and not 'me' in owners"
            if shard.owner_filter is not None:
                owner = shard.owner_filter.replace("\\", "\\\\").replace("'", "\\'")
                query += f" and '{owner}' in owners"
        field = GoogleFields.MODIFIED_TIME.value
        if shard.open_end:
            return f"{query} and {field} >= '{_iso(t0)}'"
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
        # A shortcut target that changed before the window is outside every
        # listing's range, so no other listing covers it.
        listable = not via_shortcut or self._in_window(file)

        if kind is ListingPartitionKind.SHARED_WITH_USER:
            covered = (
                file_drive_id in state.listed_drive_ids or owner in state.listed_owners
            )
            if covered and listable:
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
        # A shortcut to a file of this partition in the window: the listing
        # has the file.
        if via_shortcut and own and listable:
            return False
        # A shortcut target can be emitted twice, here and by its own exact
        # partition. Accepted: a drop here can lose a file that only a changed
        # shortcut reaches in an incremental run.
        exact = shard.exact and own and not via_shortcut
        if not exact and covered_elsewhere and listable:
            return False
        return self._admit_file(file, exact)

    def _in_window(self, file: GoogleDriveFileType) -> bool:
        """Whether the file's own modifiedTime is in the listing window, so
        the listing of its own partition returns it. A shortcut target has
        the shortcut's time in modifiedTime, so its own time is read from
        TARGET_MODIFIED_TIME_KEY. The caller holds the lock."""
        modified = _modified_ms(file)
        if RESOLVED_FROM_SHORTCUT_KEY in file and TARGET_MODIFIED_TIME_KEY in file:
            modified = _iso_ms(file[TARGET_MODIFIED_TIME_KEY])
        if modified is None:
            return False
        state = self._state
        return modified >= state.window_t0 and (
            state.open_end or modified < state.window_t1
        )

    # --- Splitting ------------------------------------------------------------

    def _try_split(
        self, shard: ListingShard, files: list[GoogleDriveFileType]
    ) -> list[int] | _SplitRefusal:
        """Splits the shard when its range should hold many pages. Returns the
        new shard ids, or why the shard keeps its page."""
        if shard.open_end:
            return _SplitRefusal.OPEN_END
        page_times = [ms for file in files if (ms := _modified_ms(file)) is not None]
        if len(page_times) < 2:
            return _SplitRefusal.DENSITY
        skip_ids = shard.skip_ids
        if shard.page_token is not None:
            # Earlier pages listed the files older than this page, if every
            # page so far came in modifiedTime order. The sub-ranges start at
            # this page's oldest file. Files that the earlier pages kept at
            # that same time are listed again, so the first sub-range skips
            # them.
            boundary = min(page_times)
            if (
                not shard.in_order
                or shard.frontier_ms is None
                or boundary < shard.frontier_ms
            ):
                return _SplitRefusal.OUT_OF_ORDER
            if boundary == shard.frontier_ms and shard.frontier_overflow:
                return _SplitRefusal.FRONTIER_OVERFLOW
            # A first sub-range that starts where this shard starts keeps the
            # ids this shard inherited: its pages dropped them, so they are
            # not in the frontier.
            inherited = shard.skip_ids if boundary <= shard.t0 else []
            kept = shard.frontier_ids if boundary == shard.frontier_ms else []
            skip_ids = list(dict.fromkeys([*inherited, *kept]))
            if len(skip_ids) > MAX_FRONTIER_IDS:
                return _SplitRefusal.FRONTIER_OVERFLOW
            shard = shard.model_copy(update={"t0": max(shard.t0, boundary)})
        if shard.t1 - shard.t0 < 2 * MIN_SHARD_MS:
            return _SplitRefusal.DENSITY
        with self._lock:
            if len(self._state.shards) >= MAX_OPEN_SHARDS:
                return _SplitRefusal.SHARD_CAP
        newest_ms = shard.newest_ms
        newest_density: float | None = None
        if newest_ms is None:
            # The first shard of a partition. The window end stands in for
            # the newest file, which overstates the range.
            could_hold, _, _ = _expected_files(shard, page_times, shard.t1 - 1, None)
            if could_hold < MIN_FILES_TO_PROBE:
                return _SplitRefusal.DENSITY
            newest_ms, newest_density = self._read_newest_page(shard)
            with self._lock:
                live = self._state.shards.get(shard.id)
                if live is not None:
                    # A later page of this shard needs no second probe.
                    live.newest_ms = newest_ms
        ranges = plan_split(shard, page_times, newest_ms, newest_density)
        if not ranges:
            return _SplitRefusal.DENSITY
        with self._lock:
            state = self._state
            if shard.id not in state.shards:
                return []
            if len(state.shards) + len(ranges) - 1 > MAX_OPEN_SHARDS:
                return _SplitRefusal.SHARD_CAP
            del state.shards[shard.id]
            children = [
                self._add_shard(
                    shard.partition,
                    shard.principal,
                    shard.exact,
                    t0,
                    t1,
                    newest_ms,
                    # Only the first sub-range starts at the shard's start.
                    skip_ids if index == 0 else None,
                    shard.owner_filter,
                )
                for index, (t0, t1) in enumerate(ranges)
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

    def _read_newest_page(self, shard: ListingShard) -> tuple[int, float | None]:
        """The modifiedTime of the newest file in the shard's range, and the
        density of the page of newest files (None when the page is not full).
        They only steer a split, so a wrong answer loses no file. A list call
        costs the same at any page size."""
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
        density = page_density(times) if full_page and len(times) > 1 else None
        return max(times), density

    # --- Failure --------------------------------------------------------------

    def _partition_failed(
        self,
        shard: ListingShard,
        failures: list[RetrievedDriveFile],
        list_again: bool,
    ) -> list[AdaptiveTask]:
        """The shard's partition cannot list: the service account can no
        longer act as its user, or Drive denied a page. Closes every shard of
        the partition and reports ``failures``. With ``list_again``, a shared
        drive goes back to pending, to list again from its start as another
        member. Otherwise the drive is incomplete."""
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
                drive_id = partition.key
                state.listed_drive_ids.discard(drive_id)
                self._checkpoint.organizer_email_by_drive_id.pop(drive_id, None)
                if list_again:
                    state.pending_partitions.insert(0, partition)
                else:
                    self._checkpoint.incomplete_drive_ids.add(drive_id)
                    if drive_id in self._requested_shared_drive_ids:
                        self._checkpoint.unreachable_target_ids.add(drive_id)
            elif partition.kind is ListingPartitionKind.MY_DRIVE:
                # Files of this owner are no longer covered, so a shared-with
                # listing that starts later keeps them.
                owner = partition.key.lower()
                state.listed_owners.discard(owner)
                # A shared-with listing that began dropped this owner's files.
                # It lists them again, and only them.
                relist = [
                    self._add_shard(
                        started_partition,
                        principal,
                        exact,
                        state.window_t0,
                        state.window_t1,
                        newest_ms=None,
                        owner_filter=owner,
                    )
                    for started_partition, principal, exact in state.started_partitions
                    if started_partition.kind is ListingPartitionKind.SHARED_WITH_USER
                    and started_partition.key.lower() != owner
                ]
                return [
                    self._page_task(shard_id) for shard_id in relist
                ] + self._plan_tasks()
            return self._plan_tasks()


def extend_window(state: DriveListingState, t1: int) -> None:
    """Moves the end of the window to ``t1`` when a resumed listing gets a
    later end. Each partition that began gets a shard for the added range.
    Pending partitions use the new end when they start."""
    if state.open_end or t1 <= state.window_t1:
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


def open_window_end(state: DriveListingState) -> None:
    """Removes the end of the window. Each partition that began gets a shard
    for the files modified at the old end or later, with no upper bound. A
    file edited during this pass then cannot move out of its range."""
    if state.open_end:
        return
    for partition, principal, exact in state.started_partitions:
        shard_id = state.next_shard_id
        state.next_shard_id += 1
        state.shards[shard_id] = ListingShard(
            id=shard_id,
            partition=partition,
            principal=principal,
            t0=state.window_t1,
            t1=state.window_t1,
            exact=exact,
            open_end=True,
        )
    state.open_end = True
