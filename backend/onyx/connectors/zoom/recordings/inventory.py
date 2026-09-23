"""Every Zoom document that still exists, for pruning and the permission doc
sync: one whose recording its host's listing still shows, however old, which
leaves deleted and trashed recordings out. Anything left out here is deleted by
pruning and made private by the doc sync, so unlike discovery this raises rather
than skips, and it walks from Zoom's launch rather than the poll window. The one
skip is a host Zoom says it has no record of, whose documents are meant to go.
The caller renews its lock only when it receives a batch, so batches go out
even when they are empty.
"""

from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone

from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.models import SlimDocument
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import ZoomRecordingEntry
from onyx.connectors.zoom.recordings.discovery import (
    EARLIEST_RECORDING_DATE,
    DiscoverySource,
    list_every_recording,
    listing_windows,
)
from onyx.connectors.zoom.recordings.models import Host, HostScope, ZoomSessionType
from onyx.connectors.zoom.recordings.processing import zoom_document_id
from onyx.connectors.zoom.recordings.recording_access import AccessResolver
from onyx.connectors.zoom.recordings.session_types import (
    is_portal_upload,
    session_type_for_recording,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_MAX_DOCUMENTS_PER_BATCH = 500
# Bounds the ids remembered to skip a recording listed twice, at about 30 MB.
# Past it a repeat listing costs one more access call, and nothing is lost.
_MAX_REMEMBERED_IDS = 250_000
# listing_windows runs a day past the end it is given, so 28 is the widest
# trailing pass that still fits in one Zoom call per host.
_TRAILING_WINDOW_DAYS = 28
# Resolving a scope makes Zoom calls but produces no documents, so without this
# a long list of meeting numbers would run past the prune's hour-long lock.
_SCOPES_PER_HEARTBEAT = 25


def zoom_slim_documents(
    client: ZoomClient,
    sources: list[DiscoverySource],
    resolve_access: AccessResolver | None,
) -> GenerateSlimDocumentOutput:
    """Rebuilds each batch on the way out. Onyx types a slim batch as a list that
    may hold a HierarchyNode, and a list is invariant, so this copy is what lets
    everything below say what it really produces."""
    for batch in _slim_batches(client, sources, resolve_access):
        yield [*batch]


def _slim_batches(
    client: ZoomClient,
    sources: list[DiscoverySource],
    resolve_access: AccessResolver | None,
) -> Iterator[list[SlimDocument]]:
    scopes: list[HostScope] = []
    proven: list[SlimDocument] = []
    emitted: set[str] = set()
    unrecognised = 0
    anchors = 0
    resolved = 0
    for source in sources:
        for scope in source.inventory_scopes(client):
            scopes.extend(scope.hosts)
            proven.extend(
                document
                for p in scope.proven
                for document in _documents(
                    {p.session_type}, p.recording, resolve_access, emitted
                )
            )
            unrecognised += len(scope.unrecognised)
            anchors += len(scope.proven)
            resolved += 1
            if resolved % _SCOPES_PER_HEARTBEAT == 0:
                yield proven
                proven = []
    if proven:
        yield proven

    hosts = _merged(scopes)
    if unrecognised and not hosts and not anchors:
        # Zoom answers the same not-found for a user or session that was deleted
        # and for one in another account, so a credential pointed at the wrong
        # account makes everything look deleted and would wipe the connector.
        # One recording Zoom did answer for proves the account is right.
        raise ConnectorValidationError(
            "Zoom recognised none of the hosts or sessions this connector names, "
            "so pruning stopped rather than delete every document it has "
            "indexed. Either they were all deleted in Zoom, or the credentials "
            "now point at a different account. To prune them anyway, replace "
            "the entries Zoom no longer has or delete the connector"
        )
    today = datetime.now(timezone.utc).date()
    windows = listing_windows(EARLIEST_RECORDING_DATE, today)
    logger.info(
        "Zoom pruning is listing %s host(s) over %s windows, about %s calls",
        len(hosts),
        len(windows),
        len(hosts) * (len(windows) + 1),
    )

    unrecognised_types: set[str] = set()
    for scope in hosts:
        yield from _host_documents(
            client, scope, windows, unrecognised_types, resolve_access, emitted
        )

    # A recording that finishes while this walk runs lands in the newest window,
    # so every host is asked for that window again once the walk is over. This
    # only narrows the race with indexing: the prune task reads the indexed ids
    # after the crawl, and #14975 closes it by reading them before.
    # TODO(subash): drop this pass once #14975 merges; it then covers nothing.
    # Read the date again here, because a walk that crossed midnight would
    # otherwise stop a day short.
    now = datetime.now(timezone.utc).date()
    trailing = listing_windows(now - timedelta(days=_TRAILING_WINDOW_DAYS), now)
    for scope in hosts:
        yield from _host_documents(
            client, scope, trailing, unrecognised_types, resolve_access, emitted
        )


def _merged(scopes: list[HostScope]) -> list[HostScope]:
    """Without this, a host that both the Group and the host list name is walked
    twice, which is another 173 calls every prune.

    The host list knows a person only by the email an admin typed and the Group
    only by Zoom's user id, so a scope carrying both, such as a Group member's,
    is what ties the two together."""
    ids_by_email = {
        _normalised(scope.host.email): scope.host.user_id
        for scope in scopes
        if scope.host.email and _normalised(scope.host.email) != scope.host.user_id
    }
    merged: dict[str, HostScope] = {}
    for scope in scopes:
        user_id = scope.host.user_id
        if scope.host.email:
            user_id = ids_by_email.get(_normalised(scope.host.email), user_id)
        if user_id != scope.host.user_id:
            scope = scope.model_copy(
                update={"host": Host(user_id=user_id, email=scope.host.email)}
            )
        seen = merged.get(user_id)
        merged[user_id] = seen.merged_with(scope) if seen else scope
    return list(merged.values())


def _normalised(email: str) -> str:
    return email.strip().lower()


def _host_documents(
    client: ZoomClient,
    scope: HostScope,
    windows: list[tuple[date, date]],
    unrecognised_types: set[str],
    resolve_access: AccessResolver | None,
    emitted: set[str],
) -> Iterator[list[SlimDocument]]:
    """Do not reach for `_UserRecordingsSource._recordings` instead. It trims to
    the poll window, so it would drop every meeting that ran while this walk was
    running, and pruning then deletes them."""
    batch: list[SlimDocument] = []

    for from_date, to_date in windows:
        for recording in list_every_recording(client, scope.host, from_date, to_date):
            batch.extend(
                _slim_documents_for(
                    recording, scope, unrecognised_types, resolve_access, emitted
                )
            )
            if len(batch) >= _MAX_DOCUMENTS_PER_BATCH:
                yield batch
                batch = []

    yield batch


def _slim_documents_for(
    recording: ZoomRecordingEntry,
    scope: HostScope,
    unrecognised_types: set[str],
    resolve_access: AccessResolver | None,
    emitted: set[str],
) -> list[SlimDocument]:
    if recording.type is not None and is_portal_upload(recording.type):
        return []

    derived = (
        session_type_for_recording(recording.type)
        if recording.type is not None
        else None
    )
    # Warn once per code. The same recording comes round in every window of every
    # prune, so warning per recording buries the log.
    if derived is None and str(recording.type) not in unrecognised_types:
        unrecognised_types.add(str(recording.type))
        logger.warning(
            "Zoom sent recording session type %r, which this connector does not "
            "recognise; such recordings are enumerated under every type in "
            "scope so pruning cannot delete them. First seen on %s",
            recording.type,
            recording.uuid,
        )

    document_types = scope.emitted_types(recording.session_id, derived)
    return _documents(document_types, recording, resolve_access, emitted)


def _documents(
    document_types: set[ZoomSessionType],
    recording: ZoomRecordingEntry,
    resolve_access: AccessResolver | None,
    emitted: set[str],
) -> list[SlimDocument]:
    """One document per type indexing may have written this recording under,
    normally one. A recording the trailing pass or a walked host lists again
    is skipped, so it costs no second access call."""
    new_ids = [
        document_id
        for document_type in document_types
        if (document_id := zoom_document_id(document_type, recording.uuid))
        not in emitted
    ]
    if not new_ids:
        return []
    if len(emitted) < _MAX_REMEMBERED_IDS:
        emitted.update(new_ids)
    access = resolve_access(recording) if resolve_access is not None else None
    created_at = _created_at(recording.start_time)
    return [
        SlimDocument(id=document_id, doc_created_at=created_at, external_access=access)
        for document_id in new_ids
    ]


def _created_at(start_time: str | None) -> datetime | None:
    """The only thing a start time we cannot read costs is one backfilled column,
    which is not worth failing a prune over."""
    if not start_time:
        return None
    try:
        return time_str_to_utc(start_time)
    except Exception:
        logger.warning("Zoom sent a start time we could not read: %r", start_time)
        return None
