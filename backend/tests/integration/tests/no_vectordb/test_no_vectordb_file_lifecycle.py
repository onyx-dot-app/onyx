"""Integration test for the full user-file lifecycle in no-vector-DB mode.

Covers: upload → COMPLETED → unlink from project → delete → gone.

The entire lifecycle is handled by FastAPI BackgroundTasks (no Celery workers
needed).  The conftest-level ``pytestmark`` ensures these tests are skipped
when the server is running with vector DB enabled.
"""

import time
from uuid import UUID

import requests

from onyx.db.enums import UserFileStatus
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.project import ProjectManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser

POLL_INTERVAL_SECONDS = 1
POLL_TIMEOUT_SECONDS = 30


def _poll_file_status(
    file_id: UUID,
    user: DATestUser,
    target_status: UserFileStatus,
    timeout: int = POLL_TIMEOUT_SECONDS,
) -> None:
    """Poll GET /user/projects/file/{file_id} until the file reaches *target_status*."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(
            f"{API_SERVER_URL}/user/projects/file/{file_id}",
            headers=user.headers,
        )
        if resp.ok:
            status = resp.json().get("status")
            if status == target_status.value:
                return
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(
        f"File {file_id} did not reach {target_status.value} within {timeout}s"
    )


def _file_is_gone(file_id: UUID, user: DATestUser, timeout: int = 15) -> None:
    """Poll until GET /user/projects/file/{file_id} returns 404."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(
            f"{API_SERVER_URL}/user/projects/file/{file_id}",
            headers=user.headers,
        )
        if resp.status_code == 404:
            return
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(
        f"File {file_id} still accessible after {timeout}s (expected 404)"
    )


def test_file_upload_process_delete_lifecycle(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """Full lifecycle: upload → COMPLETED → unlink → delete → 404.

    Validates that the API server handles all background processing
    (via FastAPI BackgroundTasks) without any Celery workers running.
    """
    project = ProjectManager.create(
        name="lifecycle-test", user_performing_action=admin_user
    )

    file_content = b"Integration test file content for lifecycle verification."
    upload_result = ProjectManager.upload_files(
        project_id=project.id,
        files=[("lifecycle.txt", file_content)],
        user_performing_action=admin_user,
    )
    assert upload_result.user_files, "Expected at least one file in upload response"

    user_file = upload_result.user_files[0]
    file_id = user_file.id

    _poll_file_status(file_id, admin_user, UserFileStatus.COMPLETED)

    project_files = ProjectManager.get_project_files(project.id, admin_user)
    assert any(
        f.id == file_id for f in project_files
    ), "File should be listed in project files after processing"

    # Unlink the file from the project so the delete endpoint will proceed
    unlink_resp = requests.delete(
        f"{API_SERVER_URL}/user/projects/{project.id}/files/{file_id}",
        headers=admin_user.headers,
    )
    assert (
        unlink_resp.status_code == 204
    ), f"Expected 204 on unlink, got {unlink_resp.status_code}: {unlink_resp.text}"

    delete_resp = requests.delete(
        f"{API_SERVER_URL}/user/projects/file/{file_id}",
        headers=admin_user.headers,
    )
    assert (
        delete_resp.ok
    ), f"Delete request failed: {delete_resp.status_code} {delete_resp.text}"
    body = delete_resp.json()
    assert (
        body["has_associations"] is False
    ), f"File still has associations after unlink: {body}"

    _file_is_gone(file_id, admin_user)

    project_files_after = ProjectManager.get_project_files(project.id, admin_user)
    assert not any(
        f.id == file_id for f in project_files_after
    ), "Deleted file should not appear in project files"


def test_delete_blocked_while_associated(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """Deleting a file that still belongs to a project should return
    has_associations=True without actually deleting the file."""
    project = ProjectManager.create(
        name="assoc-test", user_performing_action=admin_user
    )

    upload_result = ProjectManager.upload_files(
        project_id=project.id,
        files=[("assoc.txt", b"associated file content")],
        user_performing_action=admin_user,
    )
    file_id = upload_result.user_files[0].id

    _poll_file_status(file_id, admin_user, UserFileStatus.COMPLETED)

    # Attempt to delete while still linked
    delete_resp = requests.delete(
        f"{API_SERVER_URL}/user/projects/file/{file_id}",
        headers=admin_user.headers,
    )
    assert delete_resp.ok
    body = delete_resp.json()
    assert body["has_associations"] is True, "Should report existing associations"
    assert project.name in body["project_names"]

    # File should still be accessible
    get_resp = requests.get(
        f"{API_SERVER_URL}/user/projects/file/{file_id}",
        headers=admin_user.headers,
    )
    assert get_resp.status_code == 200, "File should still exist after blocked delete"
