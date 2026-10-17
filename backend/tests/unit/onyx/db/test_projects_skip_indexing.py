"""The skip_indexing upload flag stores files as SKIPPED and sends no
PROCESS_SINGLE_USER_FILE task, so nothing indexes or captions them."""

from io import BytesIO
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import UploadFile

from onyx.db import projects
from onyx.db.enums import UserFileStatus
from onyx.db.models import User
from onyx.server.features.projects.projects_file_utils import CategorizedFiles


@pytest.mark.parametrize("skip_indexing", [False, True])
def test_skip_indexing_stores_skipped_files_without_processing(
    skip_indexing: bool,
) -> None:
    uploads = [
        UploadFile(file=BytesIO(b"a"), filename="a.png"),
        UploadFile(file=BytesIO(b"b"), filename="b.png"),
    ]
    categorized = CategorizedFiles(
        acceptable=uploads,
        acceptable_file_to_token_count={"a.png": 10, "b.png": 10},
    )
    with (
        patch.object(projects, "categorize_uploaded_files", return_value=categorized),
        patch.object(
            projects, "upload_files", return_value=MagicMock(file_paths=["fa", "fb"])
        ),
        patch.object(projects, "get_current_tenant_id", return_value="test_tenant"),
        patch(
            "onyx.background.celery.versioned_apps.client.app", new_callable=MagicMock
        ) as client_app,
    ):
        result = projects.upload_files_to_user_files_with_indexing(
            files=uploads,
            project_id=None,
            user=User(id=uuid4()),
            temp_id_map=None,
            db_session=MagicMock(),
            skip_indexing=skip_indexing,
        )

    expected_status = (
        UserFileStatus.SKIPPED if skip_indexing else UserFileStatus.PROCESSING
    )
    assert [user_file.status for user_file in result.user_files] == [
        expected_status,
        expected_status,
    ]
    assert client_app.send_task.call_count == (0 if skip_indexing else len(uploads))
