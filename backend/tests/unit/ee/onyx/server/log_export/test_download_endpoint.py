import asyncio
import tempfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from ee.onyx.server.log_export import api as log_export_api
from ee.onyx.server.log_export.api import download_api_server_logs
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def test_rejected_while_export_in_progress() -> None:
    assert not log_export_api._EXPORT_LOCK.locked(), "Lock leaked from another test."
    assert log_export_api._EXPORT_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(OnyxError) as exc_info:
            download_api_server_logs()
        assert exc_info.value.error_code == OnyxErrorCode.RATE_LIMITED
    finally:
        log_export_api._EXPORT_LOCK.release()


def test_lock_released_when_build_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not log_export_api._EXPORT_LOCK.locked(), "Lock leaked from another test."

    def failing_build(*args: object, **kwargs: object) -> None:  # noqa: ARG001
        raise OSError("Disk exploded.")

    monkeypatch.setattr(log_export_api, "build_log_zip", failing_build)

    with pytest.raises(OSError):
        download_api_server_logs()

    assert not log_export_api._EXPORT_LOCK.locked()


def test_lock_released_even_if_buffer_close_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not log_export_api._EXPORT_LOCK.locked(), "Lock leaked from another test."

    monkeypatch.setattr(
        log_export_api, "get_default_log_directories", lambda: [tmp_path]
    )
    real_build = log_export_api.build_log_zip

    def build_with_broken_close(
        log_directories: Sequence[Path], scope_note: str
    ) -> tempfile.SpooledTemporaryFile[bytes]:
        zip_buffer = real_build(log_directories, scope_note)

        def broken_close() -> None:
            raise OSError("Close failed.")

        zip_buffer.close = broken_close  # ty: ignore[invalid-assignment]
        return zip_buffer

    monkeypatch.setattr(log_export_api, "build_log_zip", build_with_broken_close)

    response = download_api_server_logs()
    assert response.background is not None
    with pytest.raises(OSError):
        asyncio.run(response.background())

    assert not log_export_api._EXPORT_LOCK.locked()


def test_cleanup_releases_lock_without_body_iteration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Covers the client-disconnected-before-first-chunk path: the response's
    background task alone must release the lock, without the body generator
    ever running.
    """
    assert not log_export_api._EXPORT_LOCK.locked(), "Lock leaked from another test."

    (tmp_path / "onyx_debug.log").write_text("a log line\n")
    monkeypatch.setattr(
        log_export_api, "get_default_log_directories", lambda: [tmp_path]
    )

    response = download_api_server_logs()

    assert log_export_api._EXPORT_LOCK.locked(), (
        "Lock must be held while the response is pending."
    )
    assert response.background is not None

    asyncio.run(response.background())

    assert not log_export_api._EXPORT_LOCK.locked()
