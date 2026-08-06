from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.server.features.build.session.manager import SessionManager


@pytest.mark.parametrize("extension", ["ppt", "PPT"])
def test_legacy_powerpoint_preview_runs_the_slide_converter(extension: str) -> None:
    manager = SessionManager.__new__(SessionManager)
    sandbox_id = uuid4()
    session_id = uuid4()
    user_id = uuid4()
    manager._resolve_owned_session_and_sandbox = MagicMock(  # type: ignore[method-assign]
        return_value=(SimpleNamespace(), SimpleNamespace(id=sandbox_id))
    )
    manager._sandbox_manager = MagicMock()
    slide_paths = [
        "outputs/.pptx-preview/cache/slide-1.jpg",
        "outputs/.pptx-preview/cache/slide-2.jpg",
    ]
    manager._sandbox_manager.generate_pptx_preview.return_value = (slide_paths, True)
    presentation_path = f"outputs/quarterly review.{extension}"

    result = manager.get_pptx_preview(
        session_id,
        user_id,
        presentation_path,
    )

    assert result == {
        "slide_count": 2,
        "slide_paths": slide_paths,
        "cached": True,
    }
    manager._resolve_owned_session_and_sandbox.assert_called_once_with(
        session_id, user_id
    )
    call_kwargs = manager._sandbox_manager.generate_pptx_preview.call_args.kwargs
    assert call_kwargs["sandbox_id"] == sandbox_id
    assert call_kwargs["session_id"] == session_id
    assert call_kwargs["pptx_path"] == presentation_path
    assert call_kwargs["cache_dir"].startswith("outputs/.pptx-preview/")
    assert len(call_kwargs["cache_dir"].rsplit("/", 1)[-1]) == 12


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
        manager.get_pptx_preview(uuid4(), uuid4(), "outputs/presentation.pptx.txt")

    manager._sandbox_manager.generate_pptx_preview.assert_not_called()
