"""External-dependency-unit tests for artifact serving and the lazy index.

Runs the sharing-scope rules, the by-id serving paths, and the restore-time
lazy indexing against Postgres, with the sandbox stubbed at the manager seam.
The no-wake rule for shared viewers is load-bearing: a shared view must never
wake another user's pod.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import ArtifactType, SandboxStatus, SharingScope
from onyx.db.models import BuildSession, Sandbox, User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.db.artifact import (
    get_session_artifacts,
    upsert_artifact,
)
from onyx.server.features.build.db.build_session import get_build_session_for_viewer
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    OutputsManifestEntry,
    OutputsManifestResponse,
)
from onyx.server.features.build.session.api import _attachment_headers
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.features.build.session.session_ready import lazily_index_outputs
from tests.common.craft.stubs import StubSandboxManager
from tests.external_dependency_unit.craft.db_helpers import make_user


def _seed_artifact(
    db_session: Session,
    session: BuildSession,
    *,
    path: str = "deck.pptx",
    artifact_type: ArtifactType = ArtifactType.PPTX,
    deleted: bool = False,
) -> UUID:
    row = upsert_artifact(
        db_session,
        session_id=session.id,
        artifact_type=artifact_type,
        path=path,
        name=path,
        turn_index=1,
        size_bytes=4,
        content_hash="a" * 64,
    )
    if deleted:
        row.deleted = True
    db_session.commit()
    return row.id


def test_viewer_access_follows_sharing_scope(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    other = make_user(db_session, standard_account=True)
    db_session.commit()

    assert (
        get_build_session_for_viewer(session.id, test_user.id, db_session) is not None
    )
    assert get_build_session_for_viewer(session.id, other.id, db_session) is None

    session.sharing_scope = SharingScope.PUBLIC_ORG
    db_session.commit()
    assert get_build_session_for_viewer(session.id, other.id, db_session) is not None


def test_owner_downloads_file_by_id(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,
    sandbox: Callable[..., Sandbox],
    build_session_with_user: Callable[..., BuildSession],
    stub_sandbox_manager: StubSandboxManager,
    session_manager_with_stub: SessionManager,
) -> None:
    sandbox(user=test_user, status=SandboxStatus.RUNNING)
    session = build_session_with_user()
    artifact_id = _seed_artifact(db_session, session)
    stub_sandbox_manager.read_file_returns = b"deck"

    result = session_manager_with_stub.artifact_download_by_id(
        session.id, test_user.id, artifact_id
    )

    assert result is not None
    content, _mime, filename = result
    assert content == b"deck"
    assert filename == "deck.pptx"


def test_directory_artifact_downloads_as_zip(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,
    sandbox: Callable[..., Sandbox],
    build_session_with_user: Callable[..., BuildSession],
    stub_sandbox_manager: StubSandboxManager,
    session_manager_with_stub: SessionManager,
) -> None:
    sandbox(user=test_user, status=SandboxStatus.RUNNING)
    session = build_session_with_user()
    artifact_id = _seed_artifact(
        db_session, session, path="report", artifact_type=ArtifactType.DIRECTORY
    )
    stub_sandbox_manager.list_directory_returns = []

    result = session_manager_with_stub.artifact_download_by_id(
        session.id, test_user.id, artifact_id
    )

    assert result is not None
    _content, mime, filename = result
    assert mime == "application/zip"
    assert filename.endswith(".zip")


def test_deleted_artifact_serves_nothing(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,
    sandbox: Callable[..., Sandbox],
    build_session_with_user: Callable[..., BuildSession],
    session_manager_with_stub: SessionManager,
) -> None:
    sandbox(user=test_user, status=SandboxStatus.RUNNING)
    session = build_session_with_user()
    artifact_id = _seed_artifact(db_session, session, deleted=True)

    assert (
        session_manager_with_stub.artifact_download_by_id(
            session.id, test_user.id, artifact_id
        )
        is None
    )


def test_shared_viewer_is_served_from_a_running_pod(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,
    sandbox: Callable[..., Sandbox],
    build_session_with_user: Callable[..., BuildSession],
    stub_sandbox_manager: StubSandboxManager,
    session_manager_with_stub: SessionManager,
) -> None:
    sandbox(user=test_user, status=SandboxStatus.RUNNING)
    session = build_session_with_user()
    session.sharing_scope = SharingScope.PUBLIC_ORG
    db_session.commit()
    artifact_id = _seed_artifact(db_session, session)
    stub_sandbox_manager.read_file_returns = b"deck"
    viewer = make_user(db_session, standard_account=True)
    db_session.commit()

    result = session_manager_with_stub.artifact_download_by_id(
        session.id, viewer.id, artifact_id
    )

    assert result is not None


def test_shared_viewer_never_wakes_a_sleeping_pod(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,
    sandbox: Callable[..., Sandbox],
    build_session_with_user: Callable[..., BuildSession],
    stub_sandbox_manager: StubSandboxManager,
    session_manager_with_stub: SessionManager,
) -> None:
    sandbox(user=test_user, status=SandboxStatus.SLEEPING)
    session = build_session_with_user()
    session.sharing_scope = SharingScope.PUBLIC_ORG
    db_session.commit()
    artifact_id = _seed_artifact(db_session, session)
    viewer = make_user(db_session, standard_account=True)
    db_session.commit()

    with pytest.raises(OnyxError):
        session_manager_with_stub.artifact_download_by_id(
            session.id, viewer.id, artifact_id
        )
    assert stub_sandbox_manager.read_file_count == 0
    assert stub_sandbox_manager.provision_count == 0


def test_private_session_serves_nothing_to_others(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,
    sandbox: Callable[..., Sandbox],
    build_session_with_user: Callable[..., BuildSession],
    session_manager_with_stub: SessionManager,
) -> None:
    sandbox(user=test_user, status=SandboxStatus.RUNNING)
    session = build_session_with_user()
    artifact_id = _seed_artifact(db_session, session)
    other = make_user(db_session, standard_account=True)
    db_session.commit()

    assert (
        session_manager_with_stub.artifact_download_by_id(
            session.id, other.id, artifact_id
        )
        is None
    )


def test_preview_by_id_rejects_non_pptx(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,
    sandbox: Callable[..., Sandbox],
    build_session_with_user: Callable[..., BuildSession],
    session_manager_with_stub: SessionManager,
) -> None:
    sandbox(user=test_user, status=SandboxStatus.RUNNING)
    session = build_session_with_user()
    artifact_id = _seed_artifact(
        db_session, session, path="notes.txt", artifact_type=ArtifactType.FILE
    )

    with pytest.raises(ValueError):
        session_manager_with_stub.artifact_pptx_preview_by_id(
            session.id, test_user.id, artifact_id
        )


def test_lazy_index_fills_only_empty_sessions(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,
    sandbox: Callable[..., Sandbox],
    build_session_with_user: Callable[..., BuildSession],
    stub_sandbox_manager: StubSandboxManager,
) -> None:
    sandbox_row = sandbox(user=test_user, status=SandboxStatus.RUNNING)
    session = build_session_with_user()
    stub_sandbox_manager.outputs_manifest_returns = OutputsManifestResponse(
        entries=[
            OutputsManifestEntry(
                path="deck.pptx",
                is_directory=False,
                size=4,
                mtime_ns=1,
                sha256="a" * 64,
            )
        ]
    )

    lazily_index_outputs(db_session, stub_sandbox_manager, session.id, sandbox_row.id)
    (row,) = get_session_artifacts(db_session, session_id=session.id)
    assert row.path == "deck.pptx"
    assert row.turn_index is None
    assert stub_sandbox_manager.get_outputs_manifest_count == 1

    # A session that already has rows pays no second manifest walk.
    lazily_index_outputs(db_session, stub_sandbox_manager, session.id, sandbox_row.id)
    assert stub_sandbox_manager.get_outputs_manifest_count == 1


def test_lazy_index_failure_never_raises(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,
    sandbox: Callable[..., Sandbox],
    build_session_with_user: Callable[..., BuildSession],
    stub_sandbox_manager: StubSandboxManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox_row = sandbox(user=test_user, status=SandboxStatus.RUNNING)
    session = build_session_with_user()

    # An error class the reconciler does not swallow itself, so this reaches
    # the lazy indexer's own containment. Restore readiness must not care.
    def _boom(**_kwargs: object) -> OutputsManifestResponse:
        raise ValueError("boom")

    monkeypatch.setattr(stub_sandbox_manager, "get_outputs_manifest", _boom)
    lazily_index_outputs(db_session, stub_sandbox_manager, session.id, sandbox_row.id)
    assert get_session_artifacts(db_session, session_id=session.id) == []


def test_owner_with_sleeping_pod_gets_conflict_not_500(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,
    sandbox: Callable[..., Sandbox],
    build_session_with_user: Callable[..., BuildSession],
    session_manager_with_stub: SessionManager,
) -> None:
    sandbox(user=test_user, status=SandboxStatus.SLEEPING)
    session = build_session_with_user()
    artifact_id = _seed_artifact(db_session, session)

    with pytest.raises(OnyxError):
        session_manager_with_stub.artifact_download_by_id(
            session.id, test_user.id, artifact_id
        )


def test_provisioning_pod_gets_conflict(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,
    sandbox: Callable[..., Sandbox],
    build_session_with_user: Callable[..., BuildSession],
    session_manager_with_stub: SessionManager,
) -> None:
    sandbox(user=test_user, status=SandboxStatus.PROVISIONING)
    session = build_session_with_user()
    artifact_id = _seed_artifact(db_session, session)

    with pytest.raises(OnyxError):
        session_manager_with_stub.artifact_download_by_id(
            session.id, test_user.id, artifact_id
        )


def test_docx_export_by_id_rejects_non_markdown(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,
    sandbox: Callable[..., Sandbox],
    build_session_with_user: Callable[..., BuildSession],
    stub_sandbox_manager: StubSandboxManager,
    session_manager_with_stub: SessionManager,
) -> None:
    sandbox(user=test_user, status=SandboxStatus.RUNNING)
    session = build_session_with_user()
    artifact_id = _seed_artifact(
        db_session, session, path="deck.pptx", artifact_type=ArtifactType.PPTX
    )
    stub_sandbox_manager.read_file_returns = b"not markdown"

    with pytest.raises(ValueError):
        session_manager_with_stub.artifact_docx_export_by_id(
            session.id, test_user.id, artifact_id
        )


def test_attachment_headers_survive_hostile_filenames() -> None:
    headers = _attachment_headers('a"b\nc.md')
    disposition = headers["Content-Disposition"]
    assert "\n" not in disposition
    assert 'filename="abc.md"' in disposition
    assert "filename*=UTF-8''a%22b%0Ac.md" in disposition
    assert headers["X-Content-Type-Options"] == "nosniff"
