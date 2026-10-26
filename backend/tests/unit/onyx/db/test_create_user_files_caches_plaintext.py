"""Upload caches the text it already extracted so chat need not re-extract it."""

from io import BytesIO
from unittest.mock import MagicMock, patch

from fastapi import UploadFile

from onyx.db.projects import create_user_files
from onyx.server.features.projects.projects_file_utils import CategorizedFiles


def _upload(filename: str) -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(b"bytes"), size=5)


@patch("onyx.db.projects.store_user_file_plaintext")
@patch("onyx.db.projects.upload_files")
@patch("onyx.db.projects.categorize_uploaded_files")
def test_same_named_uploads_keep_their_own_text_and_cache_before_commit(
    mock_categorize: MagicMock,
    mock_upload: MagicMock,
    mock_store: MagicMock,
) -> None:
    first, second, image = (
        _upload("report.pdf"),
        _upload("report.pdf"),
        _upload("a.png"),
    )
    mock_categorize.return_value = CategorizedFiles(
        acceptable=[first, second, image],
        acceptable_file_to_token_count={"report.pdf": 3, "a.png": 10},
        acceptable_index_to_text={0: "first text", 1: "second text"},
    )
    mock_upload.return_value = MagicMock(file_paths=["p/1", "p/2", "p/3"])
    events: list[str] = []
    mock_store.side_effect = lambda *_args: events.append("cache")
    db_session = MagicMock()
    db_session.commit.side_effect = lambda: events.append("commit")

    result = create_user_files(
        files=[first, second, image],
        project_id=None,
        user=MagicMock(),
        db_session=db_session,
    )

    ids = [uf.id for uf in result.user_files]
    assert sorted(c.args for c in mock_store.call_args_list) == sorted(
        [(ids[0], "first text"), (ids[1], "second text")]
    )
    # A worker can claim the row once it is committed, so the cache must land first.
    assert events == ["cache", "cache", "commit"]
