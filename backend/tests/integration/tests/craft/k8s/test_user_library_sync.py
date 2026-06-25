"""User-library API sync tests in the Craft k8s integration lane."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest

from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.user_library.api import DeleteFileResponse
from onyx.server.features.build.user_library.api import UploadResponse
from tests.integration.tests.craft.k8s.k8s_fixtures import SandboxHandle
from tests.integration.tests.craft.k8s.k8s_fixtures import WorkspaceProxy
from tests.integration.tests.craft.user_library_http import delete_user_library_file
from tests.integration.tests.craft.user_library_http import list_user_library_tree
from tests.integration.tests.craft.user_library_http import make_zip_bytes
from tests.integration.tests.craft.user_library_http import upload_user_library_files
from tests.integration.tests.craft.user_library_http import upload_user_library_zip

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
)


def _library_path(workspace: WorkspaceProxy, file_path: str) -> WorkspaceProxy:
    return workspace / "managed" / "user_library" / file_path


class TestUserLibrarySync:
    def test_upload_api_syncs_file_to_running_sandbox(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()
        payload = b"spreadsheet data here"
        filename = f"sync-{uuid4().hex[:8]}.xlsx"

        response = upload_user_library_files(
            handle.api_user,
            [(filename, payload, "application/octet-stream")],
        )
        response.raise_for_status()

        _library_path(handle.workspace_path, filename).wait_for_file(
            expected=payload,
        )

    def test_upload_zip_api_syncs_nested_file(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()
        member = f"folder-{uuid4().hex[:6]}/real_file.csv"
        payload = b"row1,row2"

        response = upload_user_library_zip(
            handle.api_user,
            make_zip_bytes({member: payload}),
        )
        response.raise_for_status()

        _library_path(handle.workspace_path, f"bundle/{member}").wait_for_file(
            expected=payload,
        )

    def test_session_workspace_links_user_library_after_api_upload(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None

        payload = b"table-data"
        filename = f"table-{uuid4().hex[:8]}.csv"
        response = upload_user_library_files(
            handle.api_user,
            [(filename, payload, "text/csv")],
        )
        response.raise_for_status()

        link = (
            handle.workspace_path / "sessions" / str(handle.session_id) / "user_library"
        )
        assert link.is_symlink(), f"Expected symlink at {link}"
        assert (
            link.resolve()
            == (handle.workspace_path / "managed" / "user_library").resolve()
        )
        (link / filename).wait_for_file(expected=payload)

    def test_delete_api_removes_file_from_running_sandbox(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()
        filename = f"to-delete-{uuid4().hex[:8]}.txt"

        response = upload_user_library_files(
            handle.api_user,
            [(filename, b"bye", "text/plain")],
        )
        response.raise_for_status()
        upload_body = UploadResponse.model_validate(response.json())
        document_id = upload_body.entries[0].id
        target = _library_path(handle.workspace_path, filename)
        target.wait_for_file(expected=b"bye")

        delete_response = delete_user_library_file(handle.api_user, document_id)
        delete_response.raise_for_status()
        delete_body = DeleteFileResponse.model_validate(delete_response.json())
        assert delete_body.deleted == document_id
        assert all(
            entry.id != document_id for entry in list_user_library_tree(handle.api_user)
        )

        target.wait_for_absent()
