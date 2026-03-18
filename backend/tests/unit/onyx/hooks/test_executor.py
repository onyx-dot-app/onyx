"""Unit tests for the hook executor."""

from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from onyx.db.enums import HookFailStrategy
from onyx.db.enums import HookPoint
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.hooks.executor import execute_hook
from onyx.hooks.executor import execute_hook_sync
from onyx.hooks.executor import HookSkipped
from onyx.hooks.executor import HookSoftFailed

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PAYLOAD: dict[str, Any] = {"query": "test", "user_email": "u@example.com"}
_RESPONSE_PAYLOAD: dict[str, Any] = {"rewritten_query": "better test"}


def _make_hook(
    *,
    is_active: bool = True,
    endpoint_url: str | None = "https://hook.example.com/query",
    api_key: MagicMock | None = None,
    timeout_seconds: float = 5.0,
    fail_strategy: HookFailStrategy = HookFailStrategy.SOFT,
    hook_id: int = 1,
) -> MagicMock:
    hook = MagicMock()
    hook.is_active = is_active
    hook.endpoint_url = endpoint_url
    hook.api_key = api_key
    hook.timeout_seconds = timeout_seconds
    hook.id = hook_id
    hook.fail_strategy = fail_strategy
    return hook


def _make_api_key(value: str) -> MagicMock:
    api_key = MagicMock()
    api_key.get_value.return_value = value
    return api_key


def _make_response(
    *,
    status_code: int = 200,
    json_return: Any = _RESPONSE_PAYLOAD,
    raise_for_status_effect: Exception | None = None,
    json_side_effect: Exception | None = None,
) -> MagicMock:
    """Build a response mock with controllable raise_for_status() and json() behaviour."""
    response = MagicMock()
    response.status_code = status_code
    if raise_for_status_effect is not None:
        response.raise_for_status.side_effect = raise_for_status_effect
    if json_side_effect is not None:
        response.json.side_effect = json_side_effect
    else:
        response.json.return_value = json_return
    return response


def _setup_async_client(
    mock_client_cls: MagicMock,
    *,
    response: MagicMock | None = None,
    side_effect: Exception | None = None,
) -> AsyncMock:
    """Wire up the httpx.AsyncClient mock and return the inner client.

    If side_effect is an httpx.HTTPStatusError, it is raised from
    raise_for_status() (matching real httpx behaviour) and post() returns a
    response mock with the matching status_code set.  All other exceptions are
    raised directly from post().
    """
    mock_client = AsyncMock()

    if isinstance(side_effect, httpx.HTTPStatusError):
        # In real httpx, HTTPStatusError comes from raise_for_status(), not post().
        # Wire a response mock that raises on raise_for_status() so status_code
        # is captured before the exception fires, matching the executor's flow.
        error_response = MagicMock()
        error_response.status_code = side_effect.response.status_code
        error_response.raise_for_status.side_effect = side_effect
        mock_client.post = AsyncMock(return_value=error_response)
    else:
        mock_client.post = AsyncMock(
            side_effect=side_effect, return_value=response if not side_effect else None
        )

    mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _setup_sync_client(
    mock_client_cls: MagicMock,
    *,
    response: MagicMock | None = None,
    side_effect: Exception | None = None,
) -> MagicMock:
    """Wire up the httpx.Client mock and return the inner client.

    If side_effect is an httpx.HTTPStatusError, it is raised from
    raise_for_status() (matching real httpx behaviour) and post() returns a
    response mock with the matching status_code set.  All other exceptions are
    raised directly from post().
    """
    mock_client = MagicMock()

    if isinstance(side_effect, httpx.HTTPStatusError):
        error_response = MagicMock()
        error_response.status_code = side_effect.response.status_code
        error_response.raise_for_status.side_effect = side_effect
        mock_client.post = MagicMock(return_value=error_response)
    else:
        mock_client.post = MagicMock(
            side_effect=side_effect, return_value=response if not side_effect else None
        )

    mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
    return mock_client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Early-exit guards (no HTTP call, no DB writes)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hooks_available,hook",
    [
        # HOOKS_AVAILABLE=False exits before the DB lookup — hook is irrelevant.
        pytest.param(False, None, id="hooks_not_available"),
        pytest.param(True, None, id="hook_not_found"),
        pytest.param(True, _make_hook(is_active=False), id="hook_inactive"),
        pytest.param(True, _make_hook(endpoint_url=None), id="no_endpoint_url"),
    ],
)
async def test_early_exit_returns_skipped_with_no_db_writes(
    db_session: MagicMock,
    hooks_available: bool,
    hook: MagicMock | None,
) -> None:
    with (
        patch("onyx.hooks.executor.HOOKS_AVAILABLE", hooks_available),
        patch(
            "onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("onyx.hooks.executor.update_hook__no_commit") as mock_update,
        patch("onyx.hooks.executor.create_hook_execution_log__no_commit") as mock_log,
    ):
        result = await execute_hook(
            db_session=db_session,
            hook_point=HookPoint.QUERY_PROCESSING,
            payload=_PAYLOAD,
        )

    assert isinstance(result, HookSkipped)
    mock_update.assert_not_called()
    mock_log.assert_not_called()


# ---------------------------------------------------------------------------
# Successful HTTP call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_returns_payload_and_sets_reachable(
    db_session: MagicMock,
) -> None:
    hook = _make_hook()

    with (
        patch("onyx.hooks.executor.HOOKS_AVAILABLE", True),
        patch(
            "onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("onyx.hooks.executor.get_session_with_current_tenant"),
        patch("onyx.hooks.executor.update_hook__no_commit") as mock_update,
        patch("onyx.hooks.executor.create_hook_execution_log__no_commit") as mock_log,
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        _setup_async_client(mock_client_cls, response=_make_response())

        result = await execute_hook(
            db_session=db_session,
            hook_point=HookPoint.QUERY_PROCESSING,
            payload=_PAYLOAD,
        )

    assert result == _RESPONSE_PAYLOAD
    _, update_kwargs = mock_update.call_args
    assert update_kwargs["is_reachable"] is True
    mock_log.assert_not_called()


@pytest.mark.asyncio
async def test_non_dict_json_response_is_a_failure(db_session: MagicMock) -> None:
    """response.json() returning a non-dict (e.g. list) must be treated as failure."""
    hook = _make_hook(fail_strategy=HookFailStrategy.SOFT)

    with (
        patch("onyx.hooks.executor.HOOKS_AVAILABLE", True),
        patch(
            "onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("onyx.hooks.executor.get_session_with_current_tenant"),
        patch("onyx.hooks.executor.update_hook__no_commit"),
        patch("onyx.hooks.executor.create_hook_execution_log__no_commit") as mock_log,
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        _setup_async_client(
            mock_client_cls,
            response=_make_response(json_return=["unexpected", "list"]),
        )

        result = await execute_hook(
            db_session=db_session,
            hook_point=HookPoint.QUERY_PROCESSING,
            payload=_PAYLOAD,
        )

    assert isinstance(result, HookSoftFailed)
    _, log_kwargs = mock_log.call_args
    assert log_kwargs["is_success"] is False
    assert "non-dict" in (log_kwargs["error_message"] or "")


@pytest.mark.asyncio
async def test_json_decode_failure_is_a_failure(db_session: MagicMock) -> None:
    """response.json() raising must be treated as failure with SOFT strategy."""
    hook = _make_hook(fail_strategy=HookFailStrategy.SOFT)

    with (
        patch("onyx.hooks.executor.HOOKS_AVAILABLE", True),
        patch(
            "onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("onyx.hooks.executor.get_session_with_current_tenant"),
        patch("onyx.hooks.executor.update_hook__no_commit"),
        patch("onyx.hooks.executor.create_hook_execution_log__no_commit") as mock_log,
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        _setup_async_client(
            mock_client_cls,
            response=_make_response(json_side_effect=ValueError("not JSON")),
        )

        result = await execute_hook(
            db_session=db_session,
            hook_point=HookPoint.QUERY_PROCESSING,
            payload=_PAYLOAD,
        )

    assert isinstance(result, HookSoftFailed)
    _, log_kwargs = mock_log.call_args
    assert log_kwargs["is_success"] is False
    assert "non-JSON" in (log_kwargs["error_message"] or "")


# ---------------------------------------------------------------------------
# HTTP failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception,fail_strategy,expected_type,expect_is_reachable_false",
    [
        pytest.param(
            httpx.ConnectError("refused"),
            HookFailStrategy.SOFT,
            HookSoftFailed,
            True,
            id="connect_error_soft",
        ),
        pytest.param(
            httpx.ConnectError("refused"),
            HookFailStrategy.HARD,
            OnyxError,
            True,
            id="connect_error_hard",
        ),
        pytest.param(
            httpx.TimeoutException("timeout"),
            HookFailStrategy.SOFT,
            HookSoftFailed,
            False,
            id="timeout_soft",
        ),
        pytest.param(
            httpx.TimeoutException("timeout"),
            HookFailStrategy.HARD,
            OnyxError,
            False,
            id="timeout_hard",
        ),
        pytest.param(
            httpx.HTTPStatusError(
                "500",
                request=MagicMock(),
                response=MagicMock(status_code=500, text="error"),
            ),
            HookFailStrategy.SOFT,
            HookSoftFailed,
            False,
            id="http_status_error_soft",
        ),
        pytest.param(
            httpx.HTTPStatusError(
                "500",
                request=MagicMock(),
                response=MagicMock(status_code=500, text="error"),
            ),
            HookFailStrategy.HARD,
            OnyxError,
            False,
            id="http_status_error_hard",
        ),
    ],
)
async def test_http_failure_paths(
    db_session: MagicMock,
    exception: Exception,
    fail_strategy: HookFailStrategy,
    expected_type: type,
    expect_is_reachable_false: bool,
) -> None:
    hook = _make_hook(fail_strategy=fail_strategy)

    with (
        patch("onyx.hooks.executor.HOOKS_AVAILABLE", True),
        patch(
            "onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("onyx.hooks.executor.get_session_with_current_tenant"),
        patch("onyx.hooks.executor.update_hook__no_commit") as mock_update,
        patch("onyx.hooks.executor.create_hook_execution_log__no_commit"),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        _setup_async_client(mock_client_cls, side_effect=exception)

        if expected_type is OnyxError:
            with pytest.raises(OnyxError) as exc_info:
                await execute_hook(
                    db_session=db_session,
                    hook_point=HookPoint.QUERY_PROCESSING,
                    payload=_PAYLOAD,
                )
            assert exc_info.value.error_code is OnyxErrorCode.HOOK_EXECUTION_FAILED
        else:
            result = await execute_hook(
                db_session=db_session,
                hook_point=HookPoint.QUERY_PROCESSING,
                payload=_PAYLOAD,
            )
            assert isinstance(result, expected_type)

    if expect_is_reachable_false:
        mock_update.assert_called_once()
        _, kwargs = mock_update.call_args
        assert kwargs["is_reachable"] is False
    else:
        mock_update.assert_not_called()


# ---------------------------------------------------------------------------
# Authorization header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "api_key_value,expect_auth_header",
    [
        pytest.param("secret-token", True, id="api_key_present"),
        pytest.param(None, False, id="api_key_absent"),
    ],
)
async def test_authorization_header(
    db_session: MagicMock,
    api_key_value: str | None,
    expect_auth_header: bool,
) -> None:
    api_key = _make_api_key(api_key_value) if api_key_value else None
    hook = _make_hook(api_key=api_key)

    with (
        patch("onyx.hooks.executor.HOOKS_AVAILABLE", True),
        patch(
            "onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("onyx.hooks.executor.get_session_with_current_tenant"),
        patch("onyx.hooks.executor.update_hook__no_commit"),
        patch("onyx.hooks.executor.create_hook_execution_log__no_commit"),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = _setup_async_client(mock_client_cls, response=_make_response())

        await execute_hook(
            db_session=db_session,
            hook_point=HookPoint.QUERY_PROCESSING,
            payload=_PAYLOAD,
        )

    _, call_kwargs = mock_client.post.call_args
    if expect_auth_header:
        assert call_kwargs["headers"]["Authorization"] == f"Bearer {api_key_value}"
    else:
        assert "Authorization" not in call_kwargs["headers"]


# ---------------------------------------------------------------------------
# Persist session failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "http_exception,expected_result",
    [
        pytest.param(None, _RESPONSE_PAYLOAD, id="success_path"),
        pytest.param(httpx.ConnectError("refused"), OnyxError, id="hard_fail_path"),
    ],
)
async def test_persist_session_failure_is_swallowed(
    db_session: MagicMock,
    http_exception: Exception | None,
    expected_result: Any,
) -> None:
    """DB session failure in _persist_result must not mask the real return value or OnyxError."""
    hook = _make_hook(fail_strategy=HookFailStrategy.HARD)

    with (
        patch("onyx.hooks.executor.HOOKS_AVAILABLE", True),
        patch(
            "onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch(
            "onyx.hooks.executor.get_session_with_current_tenant",
            side_effect=RuntimeError("DB unavailable"),
        ),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        _setup_async_client(
            mock_client_cls,
            response=_make_response() if not http_exception else None,
            side_effect=http_exception,
        )

        if expected_result is OnyxError:
            with pytest.raises(OnyxError) as exc_info:
                await execute_hook(
                    db_session=db_session,
                    hook_point=HookPoint.QUERY_PROCESSING,
                    payload=_PAYLOAD,
                )
            assert exc_info.value.error_code is OnyxErrorCode.HOOK_EXECUTION_FAILED
        else:
            result = await execute_hook(
                db_session=db_session,
                hook_point=HookPoint.QUERY_PROCESSING,
                payload=_PAYLOAD,
            )
            assert result == expected_result


@pytest.mark.asyncio
async def test_is_reachable_failure_does_not_prevent_log(
    db_session: MagicMock,
) -> None:
    """is_reachable update failing (e.g. concurrent hook deletion) must not
    prevent the execution log from being written. Uses a ConnectError so the
    log session (first call) runs before the reachable session (second call)."""
    hook = _make_hook(fail_strategy=HookFailStrategy.SOFT)

    call_count = 0

    def _fail_second_call() -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "hook deleted")
        return MagicMock()

    with (
        patch("onyx.hooks.executor.HOOKS_AVAILABLE", True),
        patch(
            "onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch(
            "onyx.hooks.executor.get_session_with_current_tenant",
            side_effect=_fail_second_call,
        ),
        patch("onyx.hooks.executor.create_hook_execution_log__no_commit") as mock_log,
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        _setup_async_client(mock_client_cls, side_effect=httpx.ConnectError("refused"))

        result = await execute_hook(
            db_session=db_session,
            hook_point=HookPoint.QUERY_PROCESSING,
            payload=_PAYLOAD,
        )

    assert isinstance(result, HookSoftFailed)
    mock_log.assert_called_once()


# ---------------------------------------------------------------------------
# Sync executor smoke tests
# ---------------------------------------------------------------------------


def test_sync_success_returns_payload(db_session: MagicMock) -> None:
    hook = _make_hook()

    with (
        patch("onyx.hooks.executor.HOOKS_AVAILABLE", True),
        patch(
            "onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("onyx.hooks.executor.get_session_with_current_tenant"),
        patch("onyx.hooks.executor.update_hook__no_commit"),
        patch("onyx.hooks.executor.create_hook_execution_log__no_commit"),
        patch("httpx.Client") as mock_client_cls,
    ):
        _setup_sync_client(mock_client_cls, response=_make_response())
        result = execute_hook_sync(
            db_session=db_session,
            hook_point=HookPoint.QUERY_PROCESSING,
            payload=_PAYLOAD,
        )

    assert result == _RESPONSE_PAYLOAD


def test_sync_connect_error_soft_fail(db_session: MagicMock) -> None:
    hook = _make_hook(fail_strategy=HookFailStrategy.SOFT)

    with (
        patch("onyx.hooks.executor.HOOKS_AVAILABLE", True),
        patch(
            "onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("onyx.hooks.executor.get_session_with_current_tenant"),
        patch("onyx.hooks.executor.update_hook__no_commit"),
        patch("onyx.hooks.executor.create_hook_execution_log__no_commit"),
        patch("httpx.Client") as mock_client_cls,
    ):
        _setup_sync_client(mock_client_cls, side_effect=httpx.ConnectError("refused"))
        result = execute_hook_sync(
            db_session=db_session,
            hook_point=HookPoint.QUERY_PROCESSING,
            payload=_PAYLOAD,
        )

    assert isinstance(result, HookSoftFailed)
