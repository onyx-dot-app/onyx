"""User library sync end-to-end tests (ext-dep).

These tests pin the contract for the user library push pipeline:

- ``build_user_library_fileset`` — query CRAFT_FILE docs, read from file store,
  return a ``FileSet`` keyed by file_path.
- ``hydrate_user_library`` — single-sandbox cold-start hydration.

All tests run against real Postgres and a real ``KubernetesSandboxManager``
bound to a kind cluster. Tests seed data via the same DB-layer helpers
production uses (``store_user_file`` / ``delete_user_file``), so the
assertions reflect the real upload → sync path.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.server.features.build.db.user_library import create_directory_record
from onyx.server.features.build.db.user_library import delete_user_file
from onyx.server.features.build.db.user_library import fetch_user_file_for_user
from onyx.server.features.build.db.user_library import get_or_create_craft_connector
from onyx.server.features.build.db.user_library import set_sync_disabled
from onyx.server.features.build.db.user_library import store_user_file
from onyx.server.features.build.sandbox.user_library import build_user_library_fileset
from onyx.server.features.build.sandbox.user_library import hydrate_user_library
from onyx.server.features.build.sandbox.user_library import (
    sync_user_library_to_active_sandboxes,
)
from tests.external_dependency_unit.craft._test_helpers import make_user
from tests.external_dependency_unit.craft.conftest import SandboxHandle
from tests.external_dependency_unit.craft.conftest import WorkspaceProxy


def _library_path(workspace: WorkspaceProxy, file_path: str) -> WorkspaceProxy:
    return workspace / "managed" / "user_library" / file_path


def _seed_file(
    db_session: Session,
    user: User,
    file_path: str,
    content: bytes,
) -> str:
    """Seed a user library file via the production DB-layer helper."""
    connector_id, credential_id = get_or_create_craft_connector(db_session, user)
    doc_id, _, _ = store_user_file(
        db_session=db_session,
        user_id=user.id,
        connector_id=connector_id,
        credential_id=credential_id,
        file_path=file_path,
        content=content,
        mime_type="application/octet-stream",
    )
    db_session.commit()
    return doc_id


class TestUserLibrarySync:
    def test_hydrate_pushes_files_to_sandbox(
        self,
        db_session: Session,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Pins: hydrate_user_library writes files to the sandbox at the
        expected mount path with correct contents."""
        handle = running_sandbox()
        user = make_user(db_session)
        db_session.commit()

        content = b"spreadsheet data here"
        _seed_file(db_session, user, "test.xlsx", content)

        row, workspace = handle.provision_for(user)
        hydrate_user_library(row.id, user.id, db_session)

        target = _library_path(workspace, "test.xlsx")
        assert target.exists(), f"Expected user file at {target}"
        assert target.read_bytes() == content

    def test_sync_disabled_files_excluded(
        self,
        db_session: Session,
    ) -> None:
        """Pins: files with sync_disabled=True in doc_metadata are excluded
        from the fileset."""
        user = make_user(db_session)
        db_session.commit()

        _seed_file(db_session, user, "enabled.txt", b"yes")
        disabled_id = _seed_file(db_session, user, "disabled.txt", b"no")

        doc = fetch_user_file_for_user(db_session, disabled_id, user.id)
        set_sync_disabled(db_session, user.id, doc, sync_disabled=True)
        db_session.commit()

        fileset = build_user_library_fileset(user.id, db_session)

        assert "enabled.txt" in fileset
        assert "disabled.txt" not in fileset

    def test_directories_excluded_from_fileset(
        self,
        db_session: Session,
    ) -> None:
        """Pins: directory records are excluded from the fileset."""
        user = make_user(db_session)
        db_session.commit()

        connector_id, credential_id = get_or_create_craft_connector(db_session, user)
        create_directory_record(
            db_session=db_session,
            user_id=user.id,
            connector_id=connector_id,
            credential_id=credential_id,
            dir_path="/my_folder",
        )
        _seed_file(db_session, user, "real_file.csv", b"data")
        db_session.commit()

        fileset = build_user_library_fileset(user.id, db_session)

        assert "my_folder" not in fileset
        assert "real_file.csv" in fileset

    def test_session_workspace_links_user_library(
        self,
        db_session: Session,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Pins: setup_session_workspace creates a {session}/user_library
        symlink pointing at the sandbox-wide managed/user_library, so the
        agent sees synced files at a stable per-session path."""
        user = make_user(db_session)
        db_session.commit()

        content = b"row1,row2"
        _seed_file(db_session, user, "table.csv", content)

        handle = running_sandbox(user=user, with_session=True)
        assert handle.session_id is not None

        hydrate_user_library(handle.sandbox_id, user.id, db_session)

        link = (
            handle.workspace_path / "sessions" / str(handle.session_id) / "user_library"
        )
        assert link.is_symlink(), f"Expected symlink at {link}"
        assert (
            link.resolve()
            == (handle.workspace_path / "managed" / "user_library").resolve()
        )

        # Files visible through the session-scoped symlink.
        assert (link / "table.csv").read_bytes() == content

    def test_sync_after_delete_removes_file(
        self,
        db_session: Session,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Pins: deleting a document and re-syncing removes the file from the
        sandbox via atomic swap."""
        handle = running_sandbox()
        user = make_user(db_session)
        db_session.commit()

        doc_id = _seed_file(db_session, user, "to_delete.txt", b"bye")

        row, workspace = handle.provision_for(user)
        hydrate_user_library(row.id, user.id, db_session)
        assert _library_path(workspace, "to_delete.txt").exists()

        doc = fetch_user_file_for_user(db_session, doc_id, user.id)
        delete_user_file(db_session, doc)
        db_session.commit()

        sync_user_library_to_active_sandboxes(user.id, db_session)

        assert not _library_path(workspace, "to_delete.txt").exists()
