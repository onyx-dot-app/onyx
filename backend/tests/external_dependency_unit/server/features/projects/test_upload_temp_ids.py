"""An upload returns each file with the client's temporary ID of that file,
also for files of one name and size (`db/projects.py:create_user_files`),
and refuses temporary IDs that do not match its files. Files of one name
keep their own indexing too."""

import io
from unittest.mock import MagicMock

import pytest
from fastapi import BackgroundTasks, UploadFile
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from onyx.db.enums import UserFileStatus
from onyx.db.projects import create_user_files
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.projects import projects_file_utils
from onyx.server.features.projects.api import upload_user_files
from onyx.server.settings.models import Settings
from tests.external_dependency_unit.conftest import MakeTestUser


def _upload(
    data: bytes, filename: str = "notes.txt", content_type: str = "text/plain"
) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(data),
        filename=filename,
        size=len(data),
        headers=Headers({"content-type": content_type}),
    )


@pytest.mark.usefixtures("initialize_file_store")
def test_files_of_one_name_keep_their_own_temp_ids(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    user = make_test_user("upload-temp-ids")
    first, second = b"first words here", b"second words two"
    result = create_user_files(
        [_upload(first), _upload(second)],
        project_id=None,
        user=user,
        db_session=db_session,
        temp_ids=["temp-first", "temp-second"],
    )

    by_temp_id = {
        result.id_to_temp_id[str(user_file.id)]: user_file
        for user_file in result.user_files
    }
    store = get_default_file_store()
    assert {
        temp_id: store.read_file(user_file.file_id).read()
        for temp_id, user_file in by_temp_id.items()
    } == {"temp-first": first, "temp-second": second}


@pytest.mark.usefixtures("initialize_file_store")
def test_files_of_one_name_keep_their_own_indexing(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    """Two spreadsheets of one name, one over the token threshold: only that
    one is stored without indexing."""
    monkeypatch.setattr(
        projects_file_utils,
        "load_settings",
        lambda: Settings(file_token_count_threshold_k=1),
    )
    user = make_test_user("upload-skip-indexing")
    large = "".join(f"word{index},{index}\n" for index in range(2000)).encode()
    result = create_user_files(
        [_upload(large, "report.csv", "text/csv"), _upload(b"a,b\n", "report.csv")],
        project_id=None,
        user=user,
        db_session=db_session,
    )

    assert [user_file.status for user_file in result.user_files] == [
        UserFileStatus.SKIPPED,
        UserFileStatus.PROCESSING,
    ]
    assert result.indexable_files == result.user_files[1:]


@pytest.mark.parametrize("temp_ids", ["not json", '{"a": "b"}', "[1, 2]", '["one"]'])
def test_temp_ids_that_do_not_match_the_files_are_refused(temp_ids: str) -> None:
    db_session = MagicMock()
    with pytest.raises(OnyxError) as raised:
        upload_user_files(
            bg_tasks=BackgroundTasks(),
            files=[_upload(b"first"), _upload(b"second")],
            project_id=None,
            temp_id_map=None,
            temp_ids=temp_ids,
            incognito_session_id=None,
            user=MagicMock(),
            db_session=db_session,
        )
    assert raised.value.error_code is OnyxErrorCode.INVALID_INPUT
    assert not db_session.method_calls
