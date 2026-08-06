from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.server.features.build.session.manager import SessionManager


@pytest.mark.parametrize("extension", ["ppt", "pptx", "PPT", "PPTX"])
def test_powerpoint_preview_accepts_supported_extensions(extension: str) -> None:
    manager = SessionManager.__new__(SessionManager)
    sandbox_id = uuid4()
    session_id = uuid4()
    user_id = uuid4()
    manager._resolve_owned_session_and_sandbox = MagicMock(  # type: ignore[method-assign]
        return_value=(SimpleNamespace(), SimpleNamespace(id=sandbox_id))
    )
    manager._sandbox_manager = MagicMock()
    manager._sandbox_manager.generate_pptx_preview.return_value = (
        ["outputs/.pptx-preview/cache/slide-1.jpg"],
        False,
    )

    result = manager.get_pptx_preview(
        session_id,
        user_id,
        f"outputs/presentation.{extension}",
    )

    assert result is not None
    assert result["slide_count"] == 1
    manager._sandbox_manager.generate_pptx_preview.assert_called_once()


def test_powerpoint_preview_rejects_other_extensions() -> None:
    manager = SessionManager.__new__(SessionManager)
    manager._resolve_owned_session_and_sandbox = MagicMock(  # type: ignore[method-assign]
        return_value=(SimpleNamespace(), SimpleNamespace(id=uuid4()))
    )
    manager._sandbox_manager = MagicMock()

    with pytest.raises(
        ValueError,
        match=r"Only \.ppt and \.pptx files are supported for preview",
    ):
        manager.get_pptx_preview(uuid4(), uuid4(), "outputs/presentation.pdf")

    manager._sandbox_manager.generate_pptx_preview.assert_not_called()
