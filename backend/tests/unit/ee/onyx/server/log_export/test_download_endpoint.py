import asyncio
import tempfile
from collections.abc import MutableMapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from starlette.requests import ClientDisconnect

from ee.onyx.server.log_export import api as log_export_api
from ee.onyx.server.log_export.api import _ExpiringLock, download_api_server_logs
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def _use_tmp_log_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "onyx_debug.log").write_text("a log line\n")
    monkeypatch.setattr(
        log_export_api, "get_default_log_directories", lambda: [tmp_path]
    )


def _http_scope(spec_version: str) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "method": "GET",
        "path": "/admin/log-export/download",
        "headers": [],
    }


async def _never_receive() -> dict[str, Any]:
    await asyncio.Event().wait()
    raise AssertionError("Unreachable.")


def test_expiring_lock_ttl_steal_and_stale_release() -> None:
    now = [0.0]
    lock = _ExpiringLock(ttl_seconds=60.0, clock=lambda: now[0])

    first = lock.try_acquire()
    assert first is not None
    assert lock.try_acquire() is None

    # Expiry lets a new holder steal the hold.
    now[0] = 61.0
    second = lock.try_acquire()
    assert second is not None

    # The stale holder's release must not free the new hold.
    lock.release(first)
    assert lock.held()

    lock.release(second)
    assert not lock.held()
    # A duplicate release stays a no-op.
    lock.release(second)
    assert not lock.held()


def test_rejected_while_export_in_progress() -> None:
    assert not log_export_api._EXPORT_LOCK.held(), "Lock leaked from another test."
    token = log_export_api._EXPORT_LOCK.try_acquire()
    assert token is not None
    try:
        with pytest.raises(OnyxError) as exc_info:
            download_api_server_logs()
        assert exc_info.value.error_code == OnyxErrorCode.RATE_LIMITED
    finally:
        log_export_api._EXPORT_LOCK.release(token)


def test_lock_released_when_build_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not log_export_api._EXPORT_LOCK.held(), "Lock leaked from another test."

    def failing_build(*args: object, **kwargs: object) -> None:  # noqa: ARG001
        raise OSError("Disk exploded.")

    monkeypatch.setattr(log_export_api, "build_log_zip", failing_build)

    with pytest.raises(OSError):
        download_api_server_logs()

    assert not log_export_api._EXPORT_LOCK.held()


def test_lock_released_even_if_buffer_close_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not log_export_api._EXPORT_LOCK.held(), "Lock leaked from another test."

    _use_tmp_log_dir(monkeypatch, tmp_path)
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

    assert not log_export_api._EXPORT_LOCK.held()


def test_cleanup_releases_lock_without_body_iteration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Covers the client-disconnected-before-first-chunk path: the response's
    background task alone must release the lock, without the body generator
    ever running.
    """
    assert not log_export_api._EXPORT_LOCK.held(), "Lock leaked from another test."

    _use_tmp_log_dir(monkeypatch, tmp_path)

    response = download_api_server_logs()

    assert log_export_api._EXPORT_LOCK.held(), (
        "Lock must be held while the response is pending."
    )
    assert response.background is not None

    asyncio.run(response.background())

    assert not log_export_api._EXPORT_LOCK.held()


def test_lock_released_when_iterator_raises_mid_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Starlette skips background tasks when the body iterator raises, so the
    release must come from the generator's own ``finally``. Drives the real
    ``StreamingResponse.__call__`` rather than invoking hooks by hand.
    """
    assert not log_export_api._EXPORT_LOCK.held(), "Lock leaked from another test."

    _use_tmp_log_dir(monkeypatch, tmp_path)
    real_build = log_export_api.build_log_zip

    def build_with_broken_read(
        log_directories: Sequence[Path], scope_note: str
    ) -> tempfile.SpooledTemporaryFile[bytes]:
        zip_buffer = real_build(log_directories, scope_note)

        def broken_read(size: int = -1) -> bytes:  # noqa: ARG001
            raise OSError("Read failed.")

        zip_buffer.read = broken_read  # ty: ignore[invalid-assignment]
        return zip_buffer

    monkeypatch.setattr(log_export_api, "build_log_zip", build_with_broken_read)

    response = download_api_server_logs()

    async def send(_message: MutableMapping[str, Any]) -> None:
        return None

    with pytest.raises(OSError):
        asyncio.run(response(_http_scope("2.3"), _never_receive, send))

    assert not log_export_api._EXPORT_LOCK.held()


def test_lock_released_on_client_disconnect_mid_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not log_export_api._EXPORT_LOCK.held(), "Lock leaked from another test."

    _use_tmp_log_dir(monkeypatch, tmp_path)

    response = download_api_server_logs()

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    async def blocked_send(_message: MutableMapping[str, Any]) -> None:
        # Simulates a stalled transport so the stream cannot finish before the
        # disconnect message is observed.
        await asyncio.Event().wait()

    asyncio.run(response(_http_scope("2.3"), receive, blocked_send))

    assert not log_export_api._EXPORT_LOCK.held()


def test_leaked_hold_recovers_via_ttl_under_asgi_2_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Under ASGI >= 2.4 semantics a failing ``send`` makes Starlette raise
    ``ClientDisconnect`` before running background tasks; the generator never
    started either, so no prompt hook runs and only the TTL recovers the lock.
    """
    now = [0.0]
    test_lock = _ExpiringLock(ttl_seconds=60.0, clock=lambda: now[0])
    monkeypatch.setattr(log_export_api, "_EXPORT_LOCK", test_lock)
    _use_tmp_log_dir(monkeypatch, tmp_path)

    response = download_api_server_logs()

    async def failing_send(_message: MutableMapping[str, Any]) -> None:
        raise OSError("Transport closed.")

    with pytest.raises(ClientDisconnect):
        asyncio.run(response(_http_scope("2.4"), _never_receive, failing_send))

    # No prompt hook ran; the hold leaks until the TTL expires.
    assert test_lock.held()
    assert test_lock.try_acquire() is None
    now[0] = 61.0
    assert test_lock.try_acquire() is not None
