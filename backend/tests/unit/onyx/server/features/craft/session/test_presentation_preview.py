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
    manager._sandbox_manager.generate_document_preview.return_value = (
        slide_paths,
        True,
    )
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
    call_kwargs = manager._sandbox_manager.generate_document_preview.call_args.kwargs
    assert call_kwargs["sandbox_id"] == sandbox_id
    assert call_kwargs["session_id"] == session_id
    assert call_kwargs["document_path"] == presentation_path
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

    manager._sandbox_manager.generate_document_preview.assert_not_called()


@pytest.mark.parametrize("extension", ["pdf", "ppt", "pptx"])
def test_thumbnail_uses_owned_session_first_page_cache(extension: str) -> None:
    manager = SessionManager.__new__(SessionManager)
    sandbox_id, session_id, user_id = uuid4(), uuid4(), uuid4()
    manager._resolve_owned_session_and_sandbox = MagicMock(  # type: ignore[method-assign]
        return_value=(SimpleNamespace(), SimpleNamespace(id=sandbox_id))
    )
    manager._sandbox_manager = MagicMock()
    page = "outputs/.document-thumbnails/hash/slide-1.jpg"
    manager._sandbox_manager.generate_document_preview.return_value = ([page], False)
    manager._sandbox_manager.read_file.return_value = b"jpeg"
    assert (
        manager.get_output_thumbnail(session_id, user_id, f"outputs/report.{extension}")
        == b"jpeg"
    )
    manager._resolve_owned_session_and_sandbox.assert_called_once_with(
        session_id, user_id
    )
    arguments = manager._sandbox_manager.generate_document_preview.call_args.kwargs
    assert arguments["first_page_only"] is True
    assert arguments["cache_dir"].startswith("outputs/.document-thumbnails/")
    manager._sandbox_manager.read_file.assert_called_once_with(
        sandbox_id=sandbox_id, session_id=session_id, path=page
    )


@pytest.mark.parametrize(
    "path", ["../another/report.pdf", "/report.pdf", "outputs/report.txt"]
)
def test_thumbnail_rejects_unsafe_or_unsupported_source(path: str) -> None:
    manager = SessionManager.__new__(SessionManager)
    manager._resolve_owned_session_and_sandbox = MagicMock(  # type: ignore[method-assign]
        return_value=(SimpleNamespace(), SimpleNamespace(id=uuid4()))
    )
    manager._sandbox_manager = MagicMock()
    with pytest.raises(ValueError):
        manager.get_output_thumbnail(uuid4(), uuid4(), path)
    manager._sandbox_manager.generate_document_preview.assert_not_called()


def test_unowned_thumbnail_does_not_run_converter() -> None:
    manager = SessionManager.__new__(SessionManager)
    manager._resolve_owned_session_and_sandbox = MagicMock(return_value=None)  # type: ignore[method-assign]
    manager._sandbox_manager = MagicMock()
    assert manager.get_output_thumbnail(uuid4(), uuid4(), "outputs/report.pdf") is None
    manager._sandbox_manager.generate_document_preview.assert_not_called()


def test_provider_command_uses_current_packaged_converter_without_skill_push() -> None:
    from onyx.server.features.build.sandbox.base import document_preview_command
    from onyx.skills.built_in import BUILTIN_SKILLS_PATH

    command = document_preview_command(
        "/session/annual report.pdf",
        "/session/cache",
        "/session",
        script_path="/managed/pptx/scripts/preview.py",
        first_page_only=True,
    )
    assert command[:2] == ["python", "-c"]
    assert (
        command[2].split("\n", 1)[1]
        == (BUILTIN_SKILLS_PATH / "pptx/scripts/preview.py").read_text()
    )
    assert command[3:] == [
        "/session/annual report.pdf",
        "/session/cache",
        "--first-page",
        "--session-root",
        "/session",
    ]
