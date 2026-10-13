"""Attribute output changes to the turn that produced them.

Only a complete before/after pair can assign ownership. A failed capture leaves
previous cards intact. The caller holds the prompt slot until persistence ends.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from pathlib import PurePosixPath
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.enums import ArtifactType
from onyx.server.features.build.db.artifact import (
    get_session_artifacts,
    mark_artifact_deleted,
    upsert_artifact,
)
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.session.models import OutputSource, TurnOutputSnapshot
from onyx.utils.logger import setup_logger

logger = setup_logger()


_OWNERSHIP_CHECK_BATCH_SIZE = 32


def _read_sources(
    manager: SandboxManager, sandbox_id: UUID, session_id: UUID
) -> Mapping[str, OutputSource] | None:
    manifest = manager.get_outputs_manifest(sandbox_id, session_id, include_web=True)
    if not manifest.complete:
        return None
    sources: dict[str, OutputSource] = {}
    app_files: list[str] = []
    app_size = 0
    for entry in manifest.entries:
        revision = f"{entry.mtime_ns}:{entry.ctime_ns}:{entry.size}"
        if entry.path.startswith("web/"):
            app_files.append(f"{entry.path}\0{revision}")
            app_size += entry.size
        else:
            sources[f"outputs/{entry.path}"] = OutputSource(
                revision=revision, size=entry.size
            )
    if app_files:
        revision = hashlib.sha256("\n".join(sorted(app_files)).encode()).hexdigest()
        sources["outputs/web"] = OutputSource(revision=revision, size=app_size)
    return sources


def capture_turn_outputs(
    manager: SandboxManager, sandbox_id: UUID, session_id: UUID, turn_index: int
) -> TurnOutputSnapshot | None:
    try:
        sources = _read_sources(manager, sandbox_id, session_id)
        if sources is not None:
            return TurnOutputSnapshot(
                sandbox_id=sandbox_id,
                session_id=session_id,
                turn_index=turn_index,
                sources=sources,
            )
    except Exception:
        logger.warning(
            "Could not capture output baseline for %s", session_id, exc_info=True
        )
    return None


def persist_turn_outputs(
    db_session: Session,
    manager: SandboxManager,
    snapshot: TurnOutputSnapshot | None,
    *,
    owns_turn: Callable[[], bool],
) -> None:
    if snapshot is None:
        return
    try:
        if not owns_turn():
            return
        after = _read_sources(manager, snapshot.sandbox_id, snapshot.session_id)
        if after is None or not owns_turn():
            return
        # Callers commit the transcript before this independent artifact transaction.
        existing = {
            artifact.path: artifact
            for artifact in get_session_artifacts(
                db_session, session_id=snapshot.session_id, include_deleted=True
            )
        }
        writes = 0
        for path in sorted(after.keys() | existing.keys()):
            artifact = existing.get(path)
            if (
                artifact is not None
                and artifact.turn_index is not None
                and artifact.turn_index > snapshot.turn_index
            ):
                continue
            source = after.get(path)
            if source is None:
                # A complete inventory repairs deletions missed by an earlier scan.
                if artifact is None or artifact.deleted:
                    continue
                mark_artifact_deleted(
                    db_session, session_id=snapshot.session_id, path=path
                )
            elif snapshot.sources.get(path) != source:
                upsert_artifact(
                    db_session,
                    session_id=snapshot.session_id,
                    artifact_type=ArtifactType.WEB_APP
                    if path == "outputs/web"
                    else ArtifactType.FILE,
                    path=path,
                    name="App" if path == "outputs/web" else PurePosixPath(path).name,
                    turn_index=snapshot.turn_index,
                    size_bytes=source.size,
                    source_revision=source.revision,
                )
            else:
                continue
            writes += 1
            if writes % _OWNERSHIP_CHECK_BATCH_SIZE == 0 and not owns_turn():
                db_session.rollback()
                return
        # A slow database batch may outlive the runner or prompt-slot lease.
        if not owns_turn():
            db_session.rollback()
            return
        db_session.commit()
    except Exception:
        db_session.rollback()
        logger.warning(
            "Could not persist output cards for %s", snapshot.session_id, exc_info=True
        )
