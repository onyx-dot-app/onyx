"""Reconciles a session's outputs tree into artifact rows at turn end.

One call per owned terminal branch, while the turn still holds its prompt
slot, so the next turn never starts against a half-written index. Idempotent
because the rows are the baseline: a run skipped by a hard crash self-heals
at the next turn end. An incomplete manifest is skipped outright, missing
entries would flap rows deleted and directory hashes stale.
"""

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.cache.interface import CacheBackend
from onyx.db.models import Artifact
from onyx.server.features.build.artifact_classifier import (
    OutputEntry,
    derive_artifacts,
)
from onyx.server.features.build.db.artifact import (
    get_session_artifacts,
    mark_artifacts_deleted,
    upsert_artifact,
)
from onyx.server.features.build.packets import ArtifactPacket
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ANNOUNCE_TTL_S = 60
# The announce exists so an attached stream can render cards promptly. The
# index refetch at turn end is the completeness guarantee, so a huge first
# reconcile does not need every row on the wire.
_MAX_ANNOUNCED = 50


def _announce_key(session_id: UUID) -> str:
    return f"craft:artifact:announce:{session_id}"


def announce_artifacts(
    session_id: UUID, packets: list[ArtifactPacket], cache: CacheBackend
) -> None:
    """Hand changed rows to the SSE stream attached to this session.

    Called after commit, so a card never announces a row a reader cannot
    fetch.
    """
    if not packets:
        return
    key = _announce_key(session_id)
    for packet in packets[:_MAX_ANNOUNCED]:
        cache.rpush(key, packet.model_dump_json())
    cache.expire(key, _ANNOUNCE_TTL_S)


def pop_artifact_announcement(
    session_id: UUID, timeout_s: int, cache: CacheBackend
) -> ArtifactPacket | None:
    """BLPOP one announced artifact. None on timeout or unparseable payload."""
    result = cache.blpop([_announce_key(session_id)], timeout_s)
    if result is None:
        return None
    _key, value = result
    if isinstance(value, bytes):
        value = value.decode()
    try:
        return ArtifactPacket.model_validate_json(value)
    except ValidationError:
        logger.warning("artifact: unparseable announce %r for %s", value, session_id)
        return None


def reconcile_session_outputs(
    db_session: Session,
    sandbox_manager: SandboxManager,
    *,
    sandbox_id: UUID,
    session_id: UUID,
    turn_index: int | None,
) -> list[ArtifactPacket]:
    """Diff the sandbox outputs manifest against the artifact rows.

    Upserts rows whose content or type moved or whose path came back, flags
    rows whose path vanished, and leaves untouched rows alone so
    ``turn_index`` keeps naming the turn that last changed each artifact.
    Flushes only, the caller owns the commit and announces the returned
    packets after it.

    Returns an empty list without touching rows when the manifest is
    unavailable or incomplete: the rows stay the baseline and the next turn
    end self-heals. Unreadable entries count as incomplete because the
    delete pass would otherwise flag rows the walk merely failed to see.
    """
    try:
        manifest = sandbox_manager.get_outputs_manifest(
            sandbox_id=sandbox_id, session_id=session_id
        )
    except (RuntimeError, ValidationError):
        logger.warning(
            "Outputs manifest unavailable for session %s; skipping reconcile",
            session_id,
            exc_info=True,
        )
        return []
    if manifest.truncated or manifest.skipped_unreadable:
        logger.warning(
            "Outputs manifest incomplete for session %s "
            "(truncated=%s skipped_unreadable=%d); skipping reconcile",
            session_id,
            manifest.truncated,
            manifest.skipped_unreadable,
        )
        return []

    derived = derive_artifacts(
        [
            OutputEntry(
                path=entry.path,
                is_directory=entry.is_directory,
                size=entry.size,
                mtime_ns=entry.mtime_ns,
                sha256=entry.sha256,
            )
            for entry in manifest.entries
        ]
    )
    rows_by_path = {
        row.path: row
        for row in get_session_artifacts(
            db_session, session_id=session_id, include_deleted=True
        )
    }

    packets: list[ArtifactPacket] = []
    for artifact in derived:
        row = rows_by_path.get(artifact.path)
        unchanged = (
            row is not None
            and not row.deleted
            and row.content_hash == artifact.content_hash
            and row.type == artifact.type
        )
        if unchanged:
            continue
        updated = upsert_artifact(
            db_session,
            session_id=session_id,
            artifact_type=artifact.type,
            path=artifact.path,
            name=artifact.name,
            turn_index=turn_index,
            size_bytes=artifact.size_bytes,
            content_hash=artifact.content_hash,
        )
        packets.append(_packet_for(updated))

    derived_paths = {artifact.path for artifact in derived}
    vanished = [
        path
        for path, row in rows_by_path.items()
        if path not in derived_paths and not row.deleted
    ]
    packets.extend(
        _packet_for(row)
        for row in mark_artifacts_deleted(
            db_session, session_id=session_id, paths=vanished
        )
    )
    return packets


def _packet_for(row: Artifact) -> ArtifactPacket:
    return ArtifactPacket(
        artifact_id=row.id,
        session_id=row.session_id,
        path=row.path,
        name=row.name,
        artifact_type=row.type,
        version=row.version,
        turn_index=row.turn_index,
        size_bytes=row.size_bytes,
        deleted=row.deleted,
    )
