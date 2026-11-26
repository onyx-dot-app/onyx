from uuid import uuid4

from onyx.server.features.build.sandbox.harness_base import ONYX_VM_FILES_ROOT
from onyx.server.features.build.sandbox.models import SESSION_WORKSPACE_ROOT
from onyx.tools.tool_implementations.sandbox.models import PublishedFileView


def _view(path: str) -> PublishedFileView:
    return PublishedFileView(
        file_id=str(uuid4()), name="a.csv", path=path, size=1, mime_type="text/csv"
    )


def test_display_path_is_relative_to_the_working_directory() -> None:
    inside = f"{SESSION_WORKSPACE_ROOT}/{uuid4()}/drafts/a.csv"
    outside = f"{ONYX_VM_FILES_ROOT}/a.csv"

    assert _view(inside).display_path == "drafts/a.csv"
    assert _view(outside).display_path == outside
