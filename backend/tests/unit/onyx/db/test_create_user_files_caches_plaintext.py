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
def test_text_is_cached_per_created_file(
    mock_categorize: MagicMock,
    mock_upload: MagicMock,
    mock_store: MagicMock,
) -> None:
    doc, image = _upload("doc.pdf"), _upload("pic.png")
    mock_categorize.return_value = CategorizedFiles(
        acceptable=[doc, image],
        acceptable_file_to_token_count={"doc.pdf": 3, "pic.png": 10},
        acceptable_file_to_text={"doc.pdf": "hello world"},
    )
    mock_upload.return_value = MagicMock(file_paths=["path/doc", "path/pic"])

    result = create_user_files(
        files=[doc, image],
        project_id=None,
        user=MagicMock(),
        db_session=MagicMock(),
    )

    doc_file = next(uf for uf in result.user_files if uf.name == "doc.pdf")
    mock_store.assert_called_once_with(doc_file.id, "hello world")
