"""External-dependency unit tests for user-library sandbox sync helpers."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.server.features.build.db.user_library import create_directory_record
from onyx.server.features.build.db.user_library import fetch_user_file_for_user
from onyx.server.features.build.db.user_library import get_or_create_craft_connector
from onyx.server.features.build.db.user_library import set_sync_disabled
from onyx.server.features.build.db.user_library import store_user_file
from onyx.server.features.build.sandbox.user_library import build_user_library_fileset
from onyx.server.features.build.sandbox.user_library import hydrate_user_library
from onyx.server.features.build.sandbox.user_library import (
    sync_user_library_to_active_sandboxes,
)
from onyx.server.features.build.sandbox.user_library import USER_LIBRARY_MOUNT_PATH
from tests.common.craft.stubs import StubSandboxManager


def _seed_file(
    db_session: Session,
    user: User,
    file_path: str,
    content: bytes,
) -> str:
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


def _patch_user_library_manager(
    monkeypatch: pytest.MonkeyPatch,
    stub: StubSandboxManager,
) -> None:
    monkeypatch.setattr(
        "onyx.server.features.build.sandbox.user_library.get_sandbox_manager",
        lambda: stub,
    )


class TestUserLibraryFileset:
    def test_sync_disabled_files_excluded(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        _seed_file(db_session, test_user, "enabled.txt", b"yes")
        disabled_id = _seed_file(db_session, test_user, "disabled.txt", b"no")

        doc = fetch_user_file_for_user(db_session, disabled_id, test_user.id)
        set_sync_disabled(db_session, test_user.id, doc, sync_disabled=True)
        db_session.commit()

        fileset = build_user_library_fileset(test_user.id, db_session)

        assert fileset == {"enabled.txt": b"yes"}

    def test_directories_excluded_from_fileset(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        connector_id, credential_id = get_or_create_craft_connector(
            db_session, test_user
        )
        create_directory_record(
            db_session=db_session,
            user_id=test_user.id,
            connector_id=connector_id,
            credential_id=credential_id,
            dir_path="/my_folder",
        )
        _seed_file(db_session, test_user, "real_file.csv", b"data")
        db_session.commit()

        fileset = build_user_library_fileset(test_user.id, db_session)

        assert fileset == {"real_file.csv": b"data"}

    def test_hydrate_user_library_pushes_current_fileset_to_one_sandbox(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        stub_sandbox_manager: StubSandboxManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sandbox_row = sandbox(user=test_user, status=SandboxStatus.RUNNING)
        _seed_file(db_session, test_user, "docs/readme.md", b"hello")
        stub_sandbox_manager.write_files_to_sandbox_silent = True
        _patch_user_library_manager(monkeypatch, stub_sandbox_manager)

        result = hydrate_user_library(sandbox_row.id, test_user.id, db_session)

        assert result.succeeded == 1
        assert stub_sandbox_manager.write_files_to_sandbox_count == 1
        assert stub_sandbox_manager.last_write_files_to_sandbox_payload == {
            "sandbox_id": sandbox_row.id,
            "mount_path": USER_LIBRARY_MOUNT_PATH,
            "files": {"docs/readme.md": b"hello"},
        }

    def test_sync_user_library_pushes_to_running_sandbox(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        stub_sandbox_manager: StubSandboxManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        running = sandbox(user=test_user, status=SandboxStatus.RUNNING)
        _seed_file(db_session, test_user, "active.txt", b"active")
        stub_sandbox_manager.write_files_to_sandbox_silent = True
        _patch_user_library_manager(monkeypatch, stub_sandbox_manager)

        sync_user_library_to_active_sandboxes(test_user.id, db_session)

        assert stub_sandbox_manager.write_files_to_sandbox_count == 1
        assert stub_sandbox_manager.last_write_files_to_sandbox_payload == {
            "sandbox_id": running.id,
            "mount_path": USER_LIBRARY_MOUNT_PATH,
            "files": {"active.txt": b"active"},
        }
