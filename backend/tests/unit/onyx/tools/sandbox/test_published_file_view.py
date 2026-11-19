from uuid import uuid4

from onyx.file_store.constants import CHAT_ARTIFACT_FILE_PREFIX
from onyx.server.features.build.sandbox.models import SESSION_WORKSPACE_ROOT
from onyx.tools.tool_implementations.sandbox.models import PublishedFileView


def _view(file_id: str, path: str) -> PublishedFileView:
    return PublishedFileView(
        file_id=file_id, name="a.csv", path=path, size=1, mime_type="text/csv"
    )


def test_display_path_is_relative_only_to_the_publishing_chats_directory() -> None:
    session_id = uuid4()
    file_id = f"{CHAT_ARTIFACT_FILE_PREFIX}{session_id}-{uuid4().hex}"
    own = f"{SESSION_WORKSPACE_ROOT}/{session_id}/drafts/a.csv"
    other = f"{SESSION_WORKSPACE_ROOT}/{uuid4()}/drafts/a.csv"

    assert _view(file_id, own).display_path == "drafts/a.csv"
    assert _view(file_id, other).display_path == other
    assert _view(file_id, "/tmp/onyx/a.csv").display_path == "/tmp/onyx/a.csv"
    # A file ID that names no chat keeps the whole path
    assert _view("plain-file-id", own).display_path == own
