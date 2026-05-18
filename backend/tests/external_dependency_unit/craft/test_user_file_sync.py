"""User file sync end-to-end tests (ext-dep).

These tests pin the contract for the user file push pipeline:

- ``build_user_files_fileset`` — query CRAFT_FILE docs, read from file store,
  return a ``FileSet`` keyed by file_path.
- ``hydrate_user_files`` — single-sandbox cold-start hydration.

All tests run against real Postgres and a real ``LocalSandboxManager`` bound
to ``tmp_path``. We assert observable outcomes only — files on disk, file
contents.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.document import upsert_document_by_connector_credential_pair
from onyx.db.document import upsert_documents
from onyx.db.enums import SandboxStatus
from onyx.db.models import Document as DbDocument
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.document_index.interfaces import DocumentMetadata
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.db.user_library import get_or_create_craft_connector
from onyx.server.features.build.sandbox.user_files import build_user_files_fileset
from onyx.server.features.build.sandbox.user_files import hydrate_user_files
from onyx.server.features.build.sandbox.user_files import (
    sync_user_files_to_active_sandboxes,
)
from tests.external_dependency_unit.craft._test_helpers import make_user
from tests.external_dependency_unit.craft.conftest import SandboxHandle


def _provision_with_status(
    handle: SandboxHandle,
    db_session: Session,
    user: User,
    status: SandboxStatus = SandboxStatus.RUNNING,
) -> tuple[Sandbox, Path]:
    """Provision a sandbox for ``user`` via ``handle``, optionally overriding status.

    Returns ``(sandbox_row, workspace_path)``. If ``status`` is not RUNNING the
    row is updated after provisioning (the manager always starts with RUNNING).
    """
    workspace = handle.provision_for(user)
    row = (
        db_session.query(Sandbox)
        .filter(Sandbox.user_id == user.id)
        .order_by(Sandbox.created_at.desc())
        .first()
    )
    assert row is not None
    if status != SandboxStatus.RUNNING:
        row.status = status
        db_session.commit()
    return row, workspace


def _user_files_dir(workspace: Path) -> Path:
    return workspace / "managed" / "user_files"


def _user_file_path(workspace: Path, file_path: str) -> Path:
    return _user_files_dir(workspace) / file_path


def _seed_user_file(
    db_session: Session,
    user: User,
    file_name: str,
    content: bytes,
    *,
    sync_disabled: bool = False,
    is_directory: bool = False,
) -> str:
    """Store a file in the file store and create matching Document + cc_pair rows.

    Returns the document_id for the created record.
    """
    file_store = get_default_file_store()
    file_store.initialize()

    file_id = file_store.save_file(
        content=io.BytesIO(content),
        display_name=file_name,
        file_origin=FileOrigin.USER_FILE,
        file_type="application/octet-stream",
    )

    connector_id, credential_id = get_or_create_craft_connector(db_session, user)

    doc_id = f"CRAFT_FILE__{user.id}__{uuid4().hex[:8]}"

    doc_metadata: dict[str, object] = {
        "file_path": file_name,
        "file_size": len(content),
        "mime_type": "application/octet-stream",
    }
    if sync_disabled:
        doc_metadata["sync_disabled"] = True
    if is_directory:
        doc_metadata["is_directory"] = True

    doc = DocumentMetadata(
        connector_id=connector_id,
        credential_id=credential_id,
        document_id=doc_id,
        semantic_identifier=f"user_library/{file_name}",
        first_link=file_id,
        doc_metadata=doc_metadata,
        file_id=file_id,
    )
    upsert_documents(db_session, [doc])
    upsert_document_by_connector_credential_pair(
        db_session, connector_id, credential_id, [doc_id]
    )
    return doc_id


class TestUserFileSync:
    def test_hydrate_pushes_user_files_to_sandbox(
        self,
        db_session: Session,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Pins: hydrate_user_files writes files to the sandbox at the
        expected mount path with correct contents."""
        handle = running_sandbox()

        user = make_user(db_session)
        db_session.commit()

        content = b"spreadsheet data here"
        _seed_user_file(db_session, user, "test.xlsx", content)

        row, workspace = _provision_with_status(handle, db_session, user)

        hydrate_user_files(row.id, user.id, db_session)

        target = _user_file_path(workspace, "test.xlsx")
        assert target.exists(), f"Expected user file at {target}"
        assert target.read_bytes() == content

    def test_sync_disabled_files_excluded(
        self,
        db_session: Session,
    ) -> None:
        """Pins: files with sync_disabled=True in doc_metadata are excluded
        from the fileset returned by build_user_files_fileset."""
        user = make_user(db_session)
        db_session.commit()

        _seed_user_file(db_session, user, "enabled.txt", b"yes")
        _seed_user_file(db_session, user, "disabled.txt", b"no", sync_disabled=True)

        fileset = build_user_files_fileset(user.id, db_session)

        assert "enabled.txt" in fileset
        assert "disabled.txt" not in fileset

    def test_directories_excluded_from_fileset(
        self,
        db_session: Session,
    ) -> None:
        """Pins: documents with is_directory=True in doc_metadata are excluded
        from the fileset — only actual files are synced."""
        user = make_user(db_session)
        db_session.commit()

        _seed_user_file(db_session, user, "my_folder", b"", is_directory=True)
        _seed_user_file(db_session, user, "real_file.csv", b"data")

        fileset = build_user_files_fileset(user.id, db_session)

        assert "my_folder" not in fileset
        assert "real_file.csv" in fileset

    def test_sync_after_delete_removes_file(
        self,
        db_session: Session,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Pins: after a Document record is deleted, the next sync pushes an
        updated fileset and the file is removed from the sandbox via atomic
        swap."""
        handle = running_sandbox()

        user = make_user(db_session)
        db_session.commit()

        doc_id = _seed_user_file(db_session, user, "to_delete.txt", b"bye")

        row, workspace = _provision_with_status(handle, db_session, user)

        hydrate_user_files(row.id, user.id, db_session)
        assert _user_file_path(workspace, "to_delete.txt").exists()

        # Delete the document record (junction row first to satisfy FK).
        db_session.query(DocumentByConnectorCredentialPair).filter(
            DocumentByConnectorCredentialPair.id == doc_id
        ).delete()
        db_session.query(DbDocument).filter(DbDocument.id == doc_id).delete()
        db_session.commit()

        sync_user_files_to_active_sandboxes(user.id, db_session)

        # After sync with an empty/reduced fileset, the file should be gone.
        assert not _user_file_path(workspace, "to_delete.txt").exists()
