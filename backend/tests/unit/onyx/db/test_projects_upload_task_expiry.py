"""
Unit test verifying that the upload API path sends tasks with expires=.

The upload_files_to_user_files_with_indexing function must include expires=
on every send_task call to prevent phantom task accumulation if the worker
is down or slow.
"""

from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

from onyx.configs.constants import CELERY_USER_FILE_PROCESSING_TASK_EXPIRES
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.models import UserFile
from onyx.db.projects import upload_files_to_user_files_with_indexing


def _make_mock_user_file() -> MagicMock:
    uf = MagicMock(spec=UserFile)
    uf.id = str(uuid4())
    return uf


@patch("onyx.db.projects.get_current_tenant_id", return_value="test_tenant")
@patch("onyx.db.projects.create_user_files")
@patch(
    "onyx.background.celery.versioned_apps.client.app",
    new_callable=MagicMock,
)
def test_send_task_includes_expires(
    mock_client_app: MagicMock,
    mock_create: MagicMock,
    mock_tenant: MagicMock,  # noqa: ARG001
) -> None:
    """Every send_task call from the upload path must include expires=."""
    user_files = [_make_mock_user_file(), _make_mock_user_file()]
    mock_create.return_value = MagicMock(
        user_files=user_files,
        rejected_files=[],
        id_to_temp_id={},
        skip_indexing_filenames=set(),
        indexable_files=user_files,
    )

    mock_user = MagicMock()
    mock_db_session = MagicMock()

    upload_files_to_user_files_with_indexing(
        files=[],
        project_id=None,
        user=mock_user,
        temp_id_map=None,
        db_session=mock_db_session,
    )

    assert mock_client_app.send_task.call_count == len(user_files)

    for call in mock_client_app.send_task.call_args_list:
        assert call.args[0] == OnyxCeleryTask.PROCESS_SINGLE_USER_FILE
        assert call.kwargs.get("queue") == OnyxCeleryQueues.USER_FILE_PROCESSING
        assert (
            call.kwargs.get("expires") == CELERY_USER_FILE_PROCESSING_TASK_EXPIRES
        ), "send_task must include expires= to prevent phantom task accumulation"
