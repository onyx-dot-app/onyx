"""A metadata-only count of what a Google Drive connector will index.

The count walks the same partitions the run walks (shared drives, My Drives,
files shared with each user, requested folders), as the users the run would
list them as, with a minimal field mask and the largest page, so it costs one
list call per thousand files. Partitions are listed in parallel. The count
runs to the end unless the caller stops it. A stopped count reports a lower
bound. Files count under the shared ``DocumentTypeLabel`` vocabulary."""

import math
import threading
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict

from onyx.connectors.google_drive.constants import (
    DRIVE_FOLDER_TYPE,
    DRIVE_SHORTCUT_TYPE,
    MAX_DEDUP_DRIVE_FILE_IDS,
)
from onyx.connectors.google_drive.file_retrieval import (
    COUNT_FILE_FIELDS,
    COUNT_PAGE_SIZE,
    files_in_drive_query,
    files_in_parent_query,
    get_folders_in_parent,
    my_drive_files_query,
    oauth_files_query,
    owner_email,
)
from onyx.connectors.google_drive.models import (
    DriveCountScope,
    GDriveMimeType,
    GoogleDriveFileType,
)
from onyx.connectors.google_drive.source_operations import (
    DriveCorpus,
    GoogleDriveHttpError,
    GoogleDriveRefreshError,
    GoogleDriveSourceOperations,
)
from onyx.connectors.google_utils.google_utils import GoogleFields
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import CorpusEstimate, DocumentTypeLabel
from onyx.file_processing.file_types import OnyxMimeTypes
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import (
    PUSHBACK_OBSERVER,
    AdaptiveConcurrency,
    AdaptiveTaskPool,
    PushbackObserver,
)

logger = setup_logger()

# Most parts a shard cuts the range ahead into after one page. The page's
# density sets how many, so a sparse range is not cut into empty parts.
SHARD_SPLIT_MAX_WAYS = 64
# Drive keeps modifiedTime to the millisecond. Files inside one second are
# paged serially rather than cut any finer.
MIN_SHARD_MS = 1000
# The end of an open-ended window: a file modified later than this is not
# expected while the count runs.
SHARD_END_MARGIN_MS = 3_600_000
# Seconds between progress reports.
PROGRESS_INTERVAL_SECONDS = 5.0
# Ids kept at one modifiedTime stamp to drop a restarted page's repeats.
# Past this a restart may count a few files at that stamp again.
MAX_FRONTIER_IDS = 10_000
# A user without Drive access answers every request with this.
_NO_DRIVE_ACCESS_STATUS = 401
# What a shortcut's target is read with: enough to tell whose listing counts it.
_TARGET_FIELDS = "id, mimeType, size, driveId, owners(emailAddress)"


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


def _listed_mime_type(file: GoogleDriveFileType) -> str | None:
    """The type a listed file counts as: a shortcut counts as its target. A
    folder shortcut is not a document."""
    mime_type = file.get("mimeType", "")
    if mime_type != DRIVE_SHORTCUT_TYPE:
        return mime_type
    details = file.get("shortcutDetails") or {}
    target_type = details.get("targetMimeType")
    if not isinstance(target_type, str) or target_type == DRIVE_FOLDER_TYPE:
        return None
    return target_type


def _shortcut_target_id(file: GoogleDriveFileType) -> str | None:
    if file.get("mimeType") != DRIVE_SHORTCUT_TYPE:
        return None
    target_id = (file.get("shortcutDetails") or {}).get("targetId")
    return target_id if isinstance(target_id, str) else None


def _file_size(file: GoogleDriveFileType) -> int | None:
    """The listed size in bytes, or None when Drive lists the file without one."""
    try:
        return int(file["size"])
    except (KeyError, TypeError, ValueError):
        return None


class CountStopped(Exception):
    """The caller asked the count to stop. Planning the scope raises it too."""


# What the estimate says when the count was stopped before the scope was done.
_STOPPED_NOTE = "stopped before the whole scope was counted"


class _Shard(BaseModel):
    """One listing of a partition over the modifiedTime range [t0, t1), in
    whole milliseconds so the bounds match Drive's stamps exactly. A work
    item of this module's threads, not a model other modules read."""

    model_config = ConfigDict(frozen=True)

    variant: DriveCorpus
    user_email: str
    base_query: str
    drive_id: str | None
    # Names the partition in a skip note.
    what: str
    t0: int
    t1: int
    # Listed by the partition that owns its files, so a file here is counted
    # without being remembered. Files shared with a user, in a requested
    # folder, or in a drive only a reader can list are not: they can turn
    # up on another path, so one a listed drive or My Drive covers is skipped.
    exact: bool = True
    # The one listing an OAuth user makes. Its own files are not copies of
    # what it reaches.
    oauth: bool = False

    def at(self, t0: int, t1: int) -> "_Shard":
        return self.model_copy(update={"t0": t0, "t1": t1})


def _window_start(start: SecondsSinceUnixEpoch | None) -> int:
    return math.floor(start * 1000) if start else 0


def _window_end(end: SecondsSinceUnixEpoch | None) -> int:
    """The first millisecond after the window, which the run includes."""
    if end is not None:
        return math.floor(end * 1000) + 1
    return math.ceil(time.time() * 1000) + SHARD_END_MARGIN_MS


def _iso(ms: int) -> str:
    stamp = datetime.fromtimestamp(ms // 1000, tz=timezone.utc)
    return stamp.replace(microsecond=ms % 1000 * 1000).isoformat(
        timespec="milliseconds"
    )


def _shard_query(base_query: str, t0: int, t1: int) -> str:
    field = GoogleFields.MODIFIED_TIME.value
    return f"{base_query} and {field} >= '{_iso(t0)}' and {field} < '{_iso(t1)}'"


def _modified_ms(file: GoogleDriveFileType) -> int:
    stamp = datetime.fromisoformat(file[GoogleFields.MODIFIED_TIME.value])
    return round(stamp.timestamp() * 1000)


class _CorpusCounter:
    """Accumulates one estimate from partitions counted on several threads.
    Every partition goes into one pool: no partition's count depends on
    another's, so the phases the run walks in order all run at once here."""

    def __init__(
        self,
        ops: GoogleDriveSourceOperations,
        primary_admin_email: str,
        is_service_account: bool,
        scope: DriveCountScope,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
        should_stop: Callable[[], bool],
        on_progress: Callable[[CorpusEstimate], None],
        concurrency: AdaptiveConcurrency,
        pool: AdaptiveTaskPool,
    ) -> None:
        self._ops = ops
        self._primary_admin_email = primary_admin_email
        self._is_service_account = is_service_account
        self._scope = scope
        # One window for every partition, so an open end lands on one instant.
        self._t0 = _window_start(start)
        self._t1 = _window_end(end)
        self._should_stop = should_stop
        self._on_progress = on_progress
        self._concurrency = concurrency
        self._pool = pool
        self._lock = threading.Lock()
        self._counts: Counter[DocumentTypeLabel] = Counter()
        self._bytes: Counter[DocumentTypeLabel] = Counter()
        # Ids of files that can turn up on several paths, like the run's dedup
        # set: exact partitions never add to it.
        self._claimed_file_ids: set[str] = set()
        # Drives and My Drive owners whose own listing has begun, so a shared
        # copy of their files is dropped. Until then it is claimed instead.
        self._listed_drive_ids: set[str] = set()
        self._listed_owners: set[str] = set()
        # Set when an OAuth user's one listing begins: which files it reaches.
        self._oauth_covers: Callable[[GoogleDriveFileType], bool] | None = None
        # A folder reachable on two paths, or by a shortcut cycle, counts once
        # per user. Past the cap it may count again.
        self._visited_folders: set[tuple[str, str]] = set()
        self._last_report = time.monotonic()
        self.skipped: list[str] = []

    def count_scope(self) -> None:
        """Runs every partition of the scope on the pool. A stop in any of
        them stops the whole count."""
        scope = self._scope
        tasks: list[Callable[[], None]] = []
        if not self._is_service_account:
            # One listing covers the user's files. Drives and folders only
            # when not every corpus is already in it.
            if scope.include_my_drives or scope.include_files_shared_with_me:
                tasks.append(self.count_oauth_files)
        else:
            tasks.extend(
                lambda email=email: self.count_my_drive(email)
                for email in scope.my_drive_emails
            )
        tasks.extend(
            lambda drive_id=drive_id, email=email: self.count_shared_drive(
                drive_id, email, complete=drive_id not in scope.incomplete_drive_ids
            )
            for drive_id, email in scope.drives.items()
        )
        tasks.extend(
            lambda folder_id=folder_id, email=email: self.count_folder(folder_id, email)
            for folder_id, emails in scope.folders.items()
            for email in emails
        )
        # Shared listings last: tasks start in order, so most owners are
        # already listed and few of their files need claiming.
        if self._is_service_account and scope.include_files_shared_with_me:
            tasks.extend(
                lambda email=email: self.count_shared_with_user(email)
                for email in scope.my_drive_emails
            )
        for task in tasks:
            self._pool.add(task)
        self._pool.run()

    @property
    def total(self) -> int:
        return sum(self._counts.values())

    @property
    def by_type(self) -> dict[DocumentTypeLabel, int]:
        return dict(self._counts)

    @property
    def bytes_by_type(self) -> dict[DocumentTypeLabel, int]:
        return dict(self._bytes)

    def _skip(self, what: str) -> None:
        with self._lock:
            self.skipped.append(what)

    def _check_stop(self) -> None:
        if self._should_stop():
            raise CountStopped()

    def _count(self, file: GoogleDriveFileType, shard: _Shard) -> None:
        self._check_stop()
        mime_type = _listed_mime_type(file)
        if mime_type is None:
            return
        target_id = _shortcut_target_id(file)
        sized = file
        if target_id is None:
            if not self._admit(file, file.get("id"), shard.exact, shard.oauth):
                return
        else:
            target = self._admit_shortcut_target(file, target_id, shard.user_email)
            if target is None:
                return
            sized = target
        label = drive_document_type(mime_type)
        size = _file_size(sized)
        with self._lock:
            self._counts[label] += 1
            if size is not None:
                self._bytes[label] += size
            report = self._progress_due()
        if report is not None:
            self._on_progress(report)

    def _admit(
        self,
        file: GoogleDriveFileType,
        file_id: object,
        exact: bool,
        own_oauth: bool = False,
    ) -> bool:
        """Whether the count takes the file: not a copy of one a listing that
        has begun counts, not one already claimed. One lock, so no listing
        begins between the coverage check and the claim. Past the dedup cap a
        duplicate counts again, which over-estimates rather than exhausts
        memory."""
        with self._lock:
            if not exact and self._is_covered(file, own_oauth):
                return False
            if not isinstance(file_id, str):
                return True
            if file_id in self._claimed_file_ids:
                return False
            if not exact and len(self._claimed_file_ids) < MAX_DEDUP_DRIVE_FILE_IDS:
                self._claimed_file_ids.add(file_id)
        return True

    def _admit_shortcut_target(
        self, shortcut: GoogleDriveFileType, target_id: str, user_email: str
    ) -> GoogleDriveFileType | None:
        """The target a shortcut counts as, once: None when the target's own
        listing counts it, when another shortcut already did, or when the
        user cannot see it, as the run reads it."""
        details = shortcut.get("shortcutDetails") or {}
        target = self._ops.get_file(
            user_email=user_email,
            file_id=target_id,
            fields=_TARGET_FIELDS,
            resource_key=details.get("targetResourceKey"),
        )
        if target is None or not self._admit(target, target_id, exact=False):
            return None
        return target

    def _progress_due(self) -> CorpusEstimate | None:
        """A snapshot once per interval. The caller holds the lock."""
        now = time.monotonic()
        if now - self._last_report < PROGRESS_INTERVAL_SECONDS:
            return None
        self._last_report = now
        return CorpusEstimate(
            total_docs=sum(self._counts.values()),
            docs_by_type=dict(self._counts),
            bytes_by_type=dict(self._bytes),
            partial=True,
            detail=None,
        )

    def count_shared_drive(self, drive_id: str, email: str, complete: bool) -> None:
        """Lists the drive as the user the run plans. Only an organizer's
        listing is a complete record of the drive: another user's can miss
        limited-access folders, so its files may also arrive on another path."""
        what = f"shared drive {drive_id}"
        try:
            self._count_partition(
                self._shard(
                    variant=DriveCorpus.DRIVE,
                    user_email=email,
                    base_query=files_in_drive_query(None, None),
                    drive_id=drive_id,
                    what=what,
                    exact=complete,
                ),
                started=(
                    (lambda: self._mark_listed(self._listed_drive_ids, drive_id))
                    if complete
                    else None
                ),
            )
        except GoogleDriveHttpError as error:
            if not error.access_denied:
                raise
            self._skip(f"{what} ({email} cannot list it)")
        except GoogleDriveRefreshError:
            self._skip(f"{what} (cannot act as {email})")

    def _mark_listed(self, listed: set[str], key: str) -> None:
        with self._lock:
            listed.add(key)

    def _shard(
        self,
        *,
        variant: DriveCorpus,
        user_email: str,
        base_query: str,
        what: str,
        drive_id: str | None = None,
        exact: bool = True,
        oauth: bool = False,
    ) -> _Shard:
        """A partition's whole window."""
        return _Shard(
            variant=variant,
            user_email=user_email,
            base_query=base_query,
            drive_id=drive_id,
            what=what,
            t0=self._t0,
            t1=self._t1,
            exact=exact,
            oauth=oauth,
        )

    def count_my_drive(self, email: str) -> None:
        what = f"My Drive of {email}"
        try:
            self._count_partition(
                self._shard(
                    variant=DriveCorpus.USER,
                    user_email=email,
                    base_query=my_drive_files_query(False, None, None),
                    what=what,
                ),
                started=lambda: self._mark_listed(self._listed_owners, email.lower()),
            )
        except GoogleDriveRefreshError:
            self._skip(f"{what} (cannot act as the user)")
        except GoogleDriveHttpError as error:
            if error.status_code != _NO_DRIVE_ACCESS_STATUS:
                raise
            self._skip(f"{what} (no Drive access)")

    def _count_partition(
        self, shard: _Shard, started: Callable[[], None] | None = None
    ) -> None:
        """Counts a whole partition. Its newest file bounds the range first, so
        the cuts land inside the data instead of in the empty time after it.
        ``started`` runs once that first request has succeeded."""
        end = self._newest_ms(shard)
        if started is not None:
            started()
        if end is None:
            return
        self._count_sharded(shard.at(shard.t0, min(shard.t1, end + 1)))

    def _newest_ms(self, shard: _Shard) -> int | None:
        """Drive may answer an empty page with a token, so the listing runs
        on until a file comes or it ends."""
        self._check_stop()
        for item in self._ops.list_files(
            variant=shard.variant,
            user_email=shard.user_email,
            fields=COUNT_FILE_FIELDS,
            query=_shard_query(shard.base_query, shard.t0, shard.t1),
            drive_id=shard.drive_id,
            order_by=f"{GoogleFields.MODIFIED_TIME.value} desc",
            page_size=1,
        ):
            if not isinstance(item, str):
                return _modified_ms(item)
        return None

    def _count_sharded(self, shard: _Shard) -> None:
        """Lists the shard a page at a time in modifiedTime order. After each
        page the range still ahead is cut into parts: this thread keeps its
        page token and pages on up to the first cut, the other parts go to the
        pool as new shards. Nothing is counted twice."""
        stop_before = shard.t1
        page_token: str | None = None
        query = _shard_query(shard.base_query, shard.t0, shard.t1)
        counted = 0
        pages = 0
        # Where the page's files start, for the density the page showed. The
        # first page starts at its first file, each later one at the last
        # page's frontier.
        page_from: int | None = None
        # Files already passed at the frontier stamp. An expired page token
        # makes the gateway restart the query, and the listing is ordered, so
        # a row behind the frontier, or at it and in this set, was seen.
        frontier_ids: set[str] = set()
        while True:
            self._check_stop()
            more: str | None = None
            frontier = shard.t0 if page_from is None else page_from
            listed = 0
            pages += 1
            for item in self._ops.list_files(
                variant=shard.variant,
                user_email=shard.user_email,
                fields=COUNT_FILE_FIELDS,
                query=query,
                drive_id=shard.drive_id,
                order_by=GoogleFields.MODIFIED_TIME.value,
                page_token=page_token,
                page_size=COUNT_PAGE_SIZE,
                max_num_pages=1,
            ):
                if isinstance(item, str):
                    more = item
                    break
                self._concurrency.observe()
                modified = _modified_ms(item)
                if modified >= stop_before:
                    more = None
                    break
                if modified < frontier or (
                    modified == frontier and item.get("id") in frontier_ids
                ):
                    continue
                if modified > frontier:
                    frontier_ids.clear()
                if len(frontier_ids) < MAX_FRONTIER_IDS:
                    frontier_ids.add(item.get("id", ""))
                if page_from is None:
                    page_from = modified
                listed += 1
                frontier = modified
                self._count(item, shard)
                counted += 1
            if more is None:
                logger.debug(
                    "Shard of %s [%s, %s) done: %s files in %s pages",
                    shard.what,
                    _iso(shard.t0),
                    _iso(stop_before),
                    counted,
                    pages,
                )
                return
            page_token = more
            if page_from is not None:
                density = listed / max(frontier - page_from, 1)
                stop_before = self._cut_ahead(shard, frontier, stop_before, density)
            page_from = frontier

    def _cut_ahead(
        self, shard: _Shard, frontier: int, stop_before: int, density: float
    ) -> int:
        """Hands all but the first part of [frontier, stop_before) to the pool,
        one part per page the range should hold at ``density`` files per
        millisecond, and returns where this thread's own part ends."""
        ahead = stop_before - frontier
        expected_pages = math.ceil(density * ahead / COUNT_PAGE_SIZE)
        ways = min(expected_pages, SHARD_SPLIT_MAX_WAYS, ahead // MIN_SHARD_MS)
        if ways < 2:
            return stop_before
        width = ahead // ways
        cuts = [frontier + width * i for i in range(1, ways)]
        cuts.append(stop_before)
        for t0, t1 in zip(cuts, cuts[1:], strict=False):
            self._pool.add(self._shard_task(shard.at(t0, t1)))
        logger.debug(
            "Cut %s ahead of %s into %s parts up to %s",
            shard.what,
            _iso(frontier),
            ways,
            _iso(stop_before),
        )
        return cuts[0]

    def _shard_task(self, shard: _Shard) -> Callable[[], None]:
        def run() -> None:
            try:
                self._count_sharded(shard)
            except GoogleDriveHttpError as error:
                if not error.access_denied:
                    raise
                self._skip(f"{shard.what} (part of it could not be listed: {error})")
            except GoogleDriveRefreshError:
                self._skip(f"{shard.what} (cannot act as the user)")

        return run

    def count_shared_with_user(self, email: str) -> None:
        """Files the user sees that no listed drive or My Drive covers."""
        what = f"files shared with {email}"
        try:
            self._count_partition(
                self._shard(
                    variant=DriveCorpus.USER,
                    user_email=email,
                    base_query=my_drive_files_query(True, None, None),
                    what=what,
                    exact=False,
                )
            )
        except GoogleDriveRefreshError:
            self._skip(f"{what} (cannot act as the user)")
        except GoogleDriveHttpError as error:
            if error.status_code != _NO_DRIVE_ACCESS_STATUS:
                raise
            self._skip(f"{what} (no Drive access)")

    def _is_covered(self, file: GoogleDriveFileType, own_oauth: bool) -> bool:
        """Whether a listing that has begun counts this file. The OAuth
        listing's own files are not copies of what it reaches. The caller
        holds the lock."""
        return (
            file.get("driveId") in self._listed_drive_ids
            or owner_email(file) in self._listed_owners
            or (
                not own_oauth
                and self._oauth_covers is not None
                and self._oauth_covers(file)
            )
        )

    def count_folder(self, folder_id: str, email: str) -> None:
        """The folder's own files, sharded like a drive. Each subfolder is a
        task of its own so a deep tree spreads over the pool."""
        with self._lock:
            if (email, folder_id) in self._visited_folders:
                return
            if len(self._visited_folders) < MAX_DEDUP_DRIVE_FILE_IDS:
                self._visited_folders.add((email, folder_id))
        try:
            self._count_partition(
                self._shard(
                    variant=DriveCorpus.ALL_DRIVES,
                    user_email=email,
                    base_query=files_in_parent_query(folder_id, None, None),
                    what=f"folder {folder_id}",
                    exact=False,
                )
            )
            self._check_stop()
            for subfolder in get_folders_in_parent(self._ops, email, folder_id):
                self._pool.add(
                    lambda sub=subfolder["id"]: self.count_folder(sub, email)
                )
        except GoogleDriveHttpError as error:
            if not error.access_denied:
                raise
            self._skip(f"folder {folder_id} ({email} cannot list it)")
        except GoogleDriveRefreshError:
            self._skip(f"folder {folder_id} (cannot act as {email})")

    def count_oauth_files(self) -> None:
        """The one listing an OAuth user makes. It also reaches files in the
        drives and folders listed on their own, so it is exact only when
        nothing else is listed."""
        scope = self._scope
        corpus, query = oauth_files_query(
            scope.include_files_shared_with_me,
            scope.include_my_drives,
            scope.include_shared_drives,
            None,
            None,
        )
        self._count_partition(
            self._shard(
                variant=corpus,
                user_email=self._primary_admin_email,
                base_query=query,
                what="the connected user's files",
                exact=not (scope.drives or scope.folders),
                oauth=True,
            ),
            started=self._mark_oauth_listed,
        )

    def _mark_oauth_listed(self) -> None:
        """What the OAuth listing reaches, mirroring ``oauth_files_query``, so
        a shortcut target or folder file it also lists is not counted again."""
        scope = self._scope
        me = self._primary_admin_email.lower()

        def every_corpus(file: GoogleDriveFileType) -> bool:
            return scope.include_shared_drives or not file.get("driveId")

        def owned(file: GoogleDriveFileType) -> bool:
            return owner_email(file) == me

        def shared_outside_drives(file: GoogleDriveFileType) -> bool:
            return not file.get("driveId") and owner_email(file) not in (None, me)

        if scope.include_my_drives and scope.include_files_shared_with_me:
            covers = every_corpus
        elif scope.include_my_drives:
            covers = owned
        else:
            covers = shared_outside_drives
        with self._lock:
            self._oauth_covers = covers


def estimate_drive_corpus(
    ops: GoogleDriveSourceOperations,
    *,
    primary_admin_email: str,
    is_service_account: bool,
    plan_scope: Callable[[], DriveCountScope],
    start: SecondsSinceUnixEpoch | None,
    end: SecondsSinceUnixEpoch | None,
    should_stop: Callable[[], bool],
    on_progress: Callable[[CorpusEstimate], None],
) -> CorpusEstimate:
    """``plan_scope`` resolves what to count and may raise ``CountStopped``
    when the caller stops the count during planning."""
    try:
        scope = plan_scope()
    except CountStopped:
        return CorpusEstimate(total_docs=0, partial=True, detail=_STOPPED_NOTE)
    # The retry wrappers report every rate limit and server error they wait
    # out. The worker count follows that signal rather than a fixed guess.
    observer = PushbackObserver()
    concurrency = AdaptiveConcurrency(observer)
    counter = _CorpusCounter(
        ops,
        primary_admin_email,
        is_service_account,
        scope,
        start,
        end,
        should_stop,
        on_progress,
        concurrency,
        AdaptiveTaskPool(concurrency),
    )
    token = PUSHBACK_OBSERVER.set(observer)
    stopped = False
    try:
        counter.count_scope()
    except CountStopped:
        stopped = True
    finally:
        PUSHBACK_OBSERVER.reset(token)
    skipped = [
        f"shared drive {drive_id} (no user can list it)"
        for drive_id in scope.unlistable_drive_ids
    ]
    skipped.extend(
        f"shared drive {drive_id} (listed as a reader, so limited-access folders may be missed)"
        for drive_id in scope.incomplete_drive_ids
    )
    skipped.extend(
        f"folder {folder_id} (no user can see it)"
        for folder_id in scope.unreachable_folder_ids
    )
    skipped.extend(counter.skipped)
    if stopped:
        skipped.insert(0, _STOPPED_NOTE)
    return CorpusEstimate(
        total_docs=counter.total,
        docs_by_type=counter.by_type,
        bytes_by_type=counter.bytes_by_type,
        partial=bool(skipped),
        detail="; ".join(skipped) or None,
    )
