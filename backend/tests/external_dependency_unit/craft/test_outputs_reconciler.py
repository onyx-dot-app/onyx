"""External-dependency-unit tests for the outputs reconciler.

Runs the real DAL against Postgres so the diff semantics the panel depends on
(create, version bump, delete, resurrect, untouched turn_index) fail on
regression, with the sandbox manifest stubbed at the manager seam.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.db.enums import ArtifactType
from onyx.db.models import BuildSession
from onyx.server.features.build.db.artifact import (
    get_session_artifacts,
    upsert_artifact,
)
from onyx.server.features.build.outputs_reconciler import (
    announce_artifacts,
    pop_artifact_announcement,
    reconcile_session_outputs,
)
from onyx.server.features.build.packets import ArtifactPacket
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    OutputsManifestEntry,
    OutputsManifestResponse,
)
from tests.common.craft.stubs import StubSandboxManager


def _manifest(
    *entries: OutputsManifestEntry,
    truncated: bool = False,
    skipped_unreadable: int = 0,
) -> OutputsManifestResponse:
    return OutputsManifestResponse(
        entries=list(entries),
        truncated=truncated,
        skipped_unreadable=skipped_unreadable,
    )


def _file(path: str, sha: str, size: int = 10) -> OutputsManifestEntry:
    return OutputsManifestEntry(
        path=path, is_directory=False, size=size, mtime_ns=1, sha256=sha
    )


def _dir(path: str) -> OutputsManifestEntry:
    return OutputsManifestEntry(path=path, is_directory=True, mtime_ns=1)


def _reconcile(
    db_session: Session,
    session: BuildSession,
    manifest: OutputsManifestResponse | None,
    *,
    turn_index: int | None = 1,
) -> list[ArtifactPacket]:
    stub = StubSandboxManager()
    stub.outputs_manifest_returns = manifest
    packets = reconcile_session_outputs(
        db_session,
        stub,
        sandbox_id=uuid4(),
        session_id=session.id,
        turn_index=turn_index,
    )
    db_session.commit()
    return packets


def test_first_reconcile_creates_rows_and_packets(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    packets = _reconcile(
        db_session,
        session,
        _manifest(
            _file("deck.pptx", "a" * 64),
            _dir("web"),
            _file("web/package.json", "b" * 64),
        ),
    )

    by_path = {p.path: p for p in packets}
    assert set(by_path) == {"deck.pptx", "web"}
    assert by_path["deck.pptx"].artifact_type == ArtifactType.PPTX
    assert by_path["web"].artifact_type == ArtifactType.WEB_APP
    assert all(p.version == 1 and not p.deleted for p in packets)
    rows = get_session_artifacts(db_session, session_id=session.id)
    assert {row.path for row in rows} == {"deck.pptx", "web"}


def test_unchanged_rows_stay_untouched(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    manifest = _manifest(_file("deck.pptx", "a" * 64))
    _reconcile(db_session, session, manifest, turn_index=1)
    packets = _reconcile(db_session, session, manifest, turn_index=2)

    assert packets == []
    (row,) = get_session_artifacts(db_session, session_id=session.id)
    assert row.version == 1
    assert row.turn_index == 1


def test_content_change_bumps_version(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    _reconcile(db_session, session, _manifest(_file("deck.pptx", "a" * 64)))
    packets = _reconcile(
        db_session, session, _manifest(_file("deck.pptx", "c" * 64)), turn_index=2
    )

    (packet,) = packets
    assert packet.version == 2
    assert packet.turn_index == 2


def test_vanished_path_deletes_and_resurrect_undeletes(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    manifest = _manifest(_file("deck.pptx", "a" * 64))
    _reconcile(db_session, session, manifest)

    (deleted_packet,) = _reconcile(db_session, session, _manifest(), turn_index=2)
    assert deleted_packet.deleted
    (row,) = get_session_artifacts(
        db_session, session_id=session.id, include_deleted=True
    )
    assert row.deleted

    (resurrected,) = _reconcile(db_session, session, manifest, turn_index=3)
    assert not resurrected.deleted
    # Same content, so resurrection announces without a version bump.
    assert resurrected.version == 1


def test_truncated_manifest_leaves_rows_alone(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    _reconcile(db_session, session, _manifest(_file("deck.pptx", "a" * 64)))

    packets = _reconcile(db_session, session, _manifest(truncated=True), turn_index=2)

    assert packets == []
    (row,) = get_session_artifacts(db_session, session_id=session.id)
    assert not row.deleted


def test_manifest_failure_leaves_rows_alone(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    _reconcile(db_session, session, _manifest(_file("deck.pptx", "a" * 64)))

    # An unconfigured stub raises the RuntimeError family the backends raise.
    packets = _reconcile(db_session, session, None, turn_index=2)

    assert packets == []
    (row,) = get_session_artifacts(db_session, session_id=session.id)
    assert not row.deleted


def test_partial_manifest_never_deletes(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    _reconcile(db_session, session, _manifest(_file("deck.pptx", "a" * 64)))

    # An unreadable-tree walk returns empty entries WITHOUT truncated, which
    # must never read as "everything was deleted".
    packets = _reconcile(
        db_session, session, _manifest(skipped_unreadable=1), turn_index=2
    )

    assert packets == []
    (row,) = get_session_artifacts(db_session, session_id=session.id)
    assert not row.deleted


def test_validation_error_is_a_skip_not_a_crash(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()

    class _MalformedStub(StubSandboxManager):
        def get_outputs_manifest(
            self,
            sandbox_id: object,  # noqa: ARG002
            session_id: object,  # noqa: ARG002
        ) -> OutputsManifestResponse:
            return OutputsManifestResponse.model_validate_json("{")

    packets = reconcile_session_outputs(
        db_session,
        _MalformedStub(),
        sandbox_id=uuid4(),
        session_id=session.id,
        turn_index=1,
    )
    assert packets == []


def test_seeded_type_drift_is_corrected(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    upsert_artifact(
        db_session,
        session_id=session.id,
        artifact_type=ArtifactType.FILE,
        path="deck.pptx",
        name="deck.pptx",
        turn_index=1,
        size_bytes=10,
        content_hash="a" * 64,
    )
    db_session.commit()

    (packet,) = _reconcile(
        db_session, session, _manifest(_file("deck.pptx", "a" * 64)), turn_index=2
    )
    assert packet.artifact_type == ArtifactType.PPTX


def test_webapp_scaffold_removal_becomes_directory(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    _reconcile(
        db_session,
        session,
        _manifest(_dir("web"), _file("web/package.json", "a" * 64)),
    )

    (packet,) = _reconcile(
        db_session,
        session,
        _manifest(_dir("web"), _file("web/index.html", "b" * 64)),
        turn_index=2,
    )
    assert packet.artifact_type == ArtifactType.DIRECTORY
    assert packet.version == 2


def test_file_replaced_by_directory_keeps_one_row(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    _reconcile(db_session, session, _manifest(_file("notes", "a" * 64)))

    (packet,) = _reconcile(
        db_session,
        session,
        _manifest(_dir("notes"), _file("notes/entry.md", "b" * 64)),
        turn_index=2,
    )
    assert packet.artifact_type == ArtifactType.DIRECTORY
    rows = get_session_artifacts(db_session, session_id=session.id)
    assert [row.path for row in rows] == ["notes"]


def test_hidden_churn_yields_no_packets(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    base = _manifest(_dir("web"), _file("web/package.json", "a" * 64))
    _reconcile(db_session, session, base)

    packets = _reconcile(
        db_session,
        session,
        _manifest(
            _dir("web"),
            _file("web/package.json", "a" * 64),
            _dir("web/node_modules"),
            _file("web/node_modules/x.js", "b" * 64),
        ),
        turn_index=2,
    )
    assert packets == []


def test_sessions_are_isolated(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session_a = build_session_with_user()
    session_b = build_session_with_user()
    _reconcile(db_session, session_b, _manifest(_file("other.txt", "b" * 64)))

    _reconcile(db_session, session_a, _manifest(_file("deck.pptx", "a" * 64)))
    _reconcile(db_session, session_a, _manifest(), turn_index=2)

    (row_b,) = get_session_artifacts(db_session, session_id=session_b.id)
    assert not row_b.deleted
    cache = get_cache_backend()
    assert pop_artifact_announcement(session_b.id, timeout_s=1, cache=cache) is None


def test_none_turn_index_is_accepted(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    (packet,) = _reconcile(
        db_session, session, _manifest(_file("deck.pptx", "a" * 64)), turn_index=None
    )
    assert packet.turn_index is None


def test_announce_roundtrip(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    packets = _reconcile(db_session, session, _manifest(_file("deck.pptx", "a" * 64)))

    cache = get_cache_backend()
    announce_artifacts(session.id, packets, cache)
    popped = pop_artifact_announcement(session.id, timeout_s=1, cache=cache)
    assert popped == packets[0]
    assert pop_artifact_announcement(session.id, timeout_s=1, cache=cache) is None


def test_announce_preserves_order(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    packets = _reconcile(
        db_session,
        session,
        _manifest(
            _file("a.txt", "a" * 64),
            _file("b.txt", "b" * 64),
            _file("c.txt", "c" * 64),
        ),
    )

    cache = get_cache_backend()
    announce_artifacts(session.id, packets, cache)
    popped = [
        pop_artifact_announcement(session.id, timeout_s=1, cache=cache) for _ in packets
    ]
    assert [p.path for p in popped if p is not None] == ["a.txt", "b.txt", "c.txt"]
