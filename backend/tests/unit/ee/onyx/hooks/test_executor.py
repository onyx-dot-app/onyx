"""Unit tests for the hook executor."""

import json
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest
from pydantic import BaseModel

from ee.onyx.hooks.executor import _execute_hook_impl as execute_hook
from onyx.db.enums import HookFailStrategy
from onyx.db.enums import HookPoint
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.hooks.executor import HookSkipped
from onyx.hooks.executor import HookSoftFailed
from onyx.hooks.points.query_processing import QueryProcessingResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PAYLOAD: dict[str, Any] = {"query": "test", "user_email": "u@example.com"}
# A valid QueryProcessingResponse payload — used by success-path tests.
_RESPONSE_PAYLOAD: dict[str, Any] = {"query": "better test"}


def _make_hook(
    *,
    is_active: bool = True,
    endpoint_url: str | None = "https://hook.example.com/query",
    api_key: MagicMock | None = None,
    timeout_seconds: float = 5.0,
    fail_strategy: HookFailStrategy = HookFailStrategy.SOFT,
    hook_id: int = 1,
    is_reachable: bool | None = None,
    hook_point: HookPoint = HookPoint.QUERY_PROCESSING,
) -> MagicMock:
    hook = MagicMock()
    hook.is_active = is_active
    hook.endpoint_url = endpoint_url
    hook.api_key = api_key
    hook.timeout_seconds = timeout_seconds
    hook.id = hook_id
    hook.fail_strategy = fail_strategy
    hook.is_reachable = is_reachable
    hook.hook_point = hook_point
    return hook


def _make_api_key(value: str) -> MagicMock:
    api_key = MagicMock()
    api_key.get_value.return_value = value
    return api_key


def _make_response(
    *,
    status_code: int = 200,
    json_return: Any = _RESPONSE_PAYLOAD,
    json_side_effect: Exception | None = None,
) -> MagicMock:
    """Build a response mock with controllable json() behaviour."""
    response = MagicMock()
    response.status_code = status_code
    if json_side_effect is not None:
        response.json.side_effect = json_side_effect
    else:
        response.json.return_value = json_return
    return response


def _setup_client(
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


@pytest.mark.parametrize(
    "multi_tenant,hook",
    [
        # MULTI_TENANT=True exits before the DB lookup — hook is irrelevant.
        pytest.param(True, None, id="multi_tenant"),
        pytest.param(False, None, id="hook_not_found"),
        pytest.param(False, _make_hook(is_active=False), id="hook_inactive"),
        pytest.param(False, _make_hook(endpoint_url=None), id="no_endpoint_url"),
    ],
)
def test_early_exit_returns_skipped_with_no_db_writes(
    db_session: MagicMock,
    multi_tenant: bool,
    hook: MagicMock | None,
) -> None:
    with (
        patch("ee.onyx.hooks.executor.MULTI_TENANT", multi_tenant),
        patch(
            "ee.onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("ee.onyx.hooks.executor.update_hook__no_commit") as mock_update,
        patch(
            "ee.onyx.hooks.executor.create_hook_execution_log__no_commit"
        ) as mock_log,
    ):
        result = execute_hook(
            db_session=db_session,
            hook_point=HookPoint.QUERY_PROCESSING,
            payload=_PAYLOAD,
            response_type=QueryProcessingResponse,
        )

    assert isinstance(result, HookSkipped)
    mock_update.assert_not_called()
    mock_log.assert_not_called()


# ---------------------------------------------------------------------------
# Successful HTTP call
# ---------------------------------------------------------------------------


def test_success_returns_validated_model_and_sets_reachable(
    db_session: MagicMock,
) -> None:
    hook = _make_hook()

    with (
        patch("ee.onyx.hooks.executor.MULTI_TENANT", False),
        patch(
            "ee.onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("ee.onyx.hooks.executor.get_session_with_current_tenant"),
        patch("ee.onyx.hooks.executor.update_hook__no_commit") as mock_update,
        patch(
            "ee.onyx.hooks.executor.create_hook_execution_log__no_commit"
        ) as mock_log,
        patch("httpx.Client") as mock_client_cls,
    ):
        _setup_client(mock_client_cls, response=_make_response())
        result = execute_hook(
            db_session=db_session,
            hook_point=HookPoint.QUERY_PROCESSING,
            payload=_PAYLOAD,
            response_type=QueryProcessingResponse,
        )

    assert isinstance(result, QueryProcessingResponse)
    assert result.query == _RESPONSE_PAYLOAD["query"]
    _, update_kwargs = mock_update.call_args
    assert update_kwargs["is_reachable"] is True
    mock_log.assert_not_called()


def test_success_skips_reachable_write_when_already_true(db_session: MagicMock) -> None:
    """Deduplication guard: a hook already at is_reachable=True that succeeds
    must not trigger a DB write."""
    hook = _make_hook(is_reachable=True)

    with (
        patch("ee.onyx.hooks.executor.MULTI_TENANT", False),
        patch(
            "ee.onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("ee.onyx.hooks.executor.get_session_with_current_tenant"),
        patch("ee.onyx.hooks.executor.update_hook__no_commit") as mock_update,
        patch("ee.onyx.hooks.executor.create_hook_execution_log__no_commit"),
        patch("httpx.Client") as mock_client_cls,
    ):
        _setup_client(mock_client_cls, response=_make_response())
        result = execute_hook(
            db_session=db_session,
            hook_point=HookPoint.QUERY_PROCESSING,
            payload=_PAYLOAD,
            response_type=QueryProcessingResponse,
        )

    assert isinstance(result, QueryProcessingResponse)
    assert result.query == _RESPONSE_PAYLOAD["query"]
    mock_update.assert_not_called()


def test_non_dict_json_response_is_a_failure(db_session: MagicMock) -> None:
    """response.json() returning a non-dict (e.g. list) must be treated as failure.
    The server responded, so is_reachable is not updated."""
    hook = _make_hook(fail_strategy=HookFailStrategy.SOFT)

    with (
        patch("ee.onyx.hooks.executor.MULTI_TENANT", False),
        patch(
            "ee.onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("ee.onyx.hooks.executor.get_session_with_current_tenant"),
        patch("ee.onyx.hooks.executor.update_hook__no_commit") as mock_update,
        patch(
            "ee.onyx.hooks.executor.create_hook_execution_log__no_commit"
        ) as mock_log,
        patch("httpx.Client") as mock_client_cls,
    ):
        _setup_client(
            mock_client_cls,
            response=_make_response(json_return=["unexpected", "list"]),
        )
        result = execute_hook(
            db_session=db_session,
            hook_point=HookPoint.QUERY_PROCESSING,
            payload=_PAYLOAD,
            response_type=QueryProcessingResponse,
        )

    assert isinstance(result, HookSoftFailed)
    _, log_kwargs = mock_log.call_args
    assert log_kwargs["is_success"] is False
    assert "non-dict" in (log_kwargs["error_message"] or "")
    mock_update.assert_not_called()


def test_json_decode_failure_is_a_failure(db_session: MagicMock) -> None:
    """response.json() raising must be treated as failure with SOFT strategy.
    The server responded, so is_reachable is not updated."""
    hook = _make_hook(fail_strategy=HookFailStrategy.SOFT)

    with (
        patch("ee.onyx.hooks.executor.MULTI_TENANT", False),
        patch(
            "ee.onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("ee.onyx.hooks.executor.get_session_with_current_tenant"),
        patch("ee.onyx.hooks.executor.update_hook__no_commit") as mock_update,
        patch(
            "ee.onyx.hooks.executor.create_hook_execution_log__no_commit"
        ) as mock_log,
        patch("httpx.Client") as mock_client_cls,
    ):
        _setup_client(
            mock_client_cls,
            response=_make_response(
                json_side_effect=json.JSONDecodeError("not JSON", "", 0)
            ),
        )
        result = execute_hook(
            db_session=db_session,
            hook_point=HookPoint.QUERY_PROCESSING,
            payload=_PAYLOAD,
            response_type=QueryProcessingResponse,
        )

    assert isinstance(result, HookSoftFailed)
    _, log_kwargs = mock_log.call_args
    assert log_kwargs["is_success"] is False
    assert "non-JSON" in (log_kwargs["error_message"] or "")
    mock_update.assert_not_called()


# ---------------------------------------------------------------------------
# HTTP failure paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exception,fail_strategy,expected_type,expected_is_reachable",
    [
        # NetworkError → is_reachable=False
        pytest.param(
            httpx.ConnectError("refused"),
            HookFailStrategy.SOFT,
            HookSoftFailed,
            False,
            id="connect_error_soft",
        ),
        pytest.param(
            httpx.ConnectError("refused"),
            HookFailStrategy.HARD,
            OnyxError,
            False,
            id="connect_error_hard",
        ),
        # 401/403 → is_reachable=False (api_key revoked)
        pytest.param(
            httpx.HTTPStatusError(
                "401",
                request=MagicMock(),
                response=MagicMock(status_code=401, text="Unauthorized"),
            ),
            HookFailStrategy.SOFT,
            HookSoftFailed,
            False,
            id="auth_401_soft",
        ),
        pytest.param(
            httpx.HTTPStatusError(
                "403",
                request=MagicMock(),
                response=MagicMock(status_code=403, text="Forbidden"),
            ),
            HookFailStrategy.HARD,
            OnyxError,
            False,
            id="auth_403_hard",
        ),
        # TimeoutException → no is_reachable write (None)
        pytest.param(
            httpx.TimeoutException("timeout"),
            HookFailStrategy.SOFT,
            HookSoftFailed,
            None,
            id="timeout_soft",
        ),
        pytest.param(
            httpx.TimeoutException("timeout"),
            HookFailStrategy.HARD,
            OnyxError,
            None,
            id="timeout_hard",
        ),
        # Other HTTP errors → no is_reachable write (None)
        pytest.param(
            httpx.HTTPStatusError(
                "500",
                request=MagicMock(),
                response=MagicMock(status_code=500, text="error"),
            ),
            HookFailStrategy.SOFT,
            HookSoftFailed,
            None,
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
            None,
            id="http_status_error_hard",
        ),
    ],
)
def test_http_failure_paths(
    db_session: MagicMock,
    exception: Exception,
    fail_strategy: HookFailStrategy,
    expected_type: type,
    expected_is_reachable: bool | None,
) -> None:
    hook = _make_hook(fail_strategy=fail_strategy)

    with (
        patch("ee.onyx.hooks.executor.MULTI_TENANT", False),
        patch(
            "ee.onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("ee.onyx.hooks.executor.get_session_with_current_tenant"),
        patch("ee.onyx.hooks.executor.update_hook__no_commit") as mock_update,
        patch("ee.onyx.hooks.executor.create_hook_execution_log__no_commit"),
        patch("httpx.Client") as mock_client_cls,
    ):
        _setup_client(mock_client_cls, side_effect=exception)

        if expected_type is OnyxError:
            with pytest.raises(OnyxError) as exc_info:
                execute_hook(
                    db_session=db_session,
                    hook_point=HookPoint.QUERY_PROCESSING,
                    payload=_PAYLOAD,
                    response_type=QueryProcessingResponse,
                )
            assert exc_info.value.error_code is OnyxErrorCode.HOOK_EXECUTION_FAILED
        else:
            result = execute_hook(
                db_session=db_session,
                hook_point=HookPoint.QUERY_PROCESSING,
                payload=_PAYLOAD,
                response_type=QueryProcessingResponse,
            )
            assert isinstance(result, expected_type)

    if expected_is_reachable is None:
        mock_update.assert_not_called()
    else:
        mock_update.assert_called_once()
        _, kwargs = mock_update.call_args
        assert kwargs["is_reachable"] is expected_is_reachable


# ---------------------------------------------------------------------------
# Authorization header
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "api_key_value,expect_auth_header",
    [
        pytest.param("secret-token", True, id="api_key_present"),
        pytest.param(None, False, id="api_key_absent"),
    ],
)
def test_authorization_header(
    db_session: MagicMock,
    api_key_value: str | None,
    expect_auth_header: bool,
) -> None:
    api_key = _make_api_key(api_key_value) if api_key_value else None
    hook = _make_hook(api_key=api_key)

    with (
        patch("ee.onyx.hooks.executor.MULTI_TENANT", False),
        patch(
            "ee.onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("ee.onyx.hooks.executor.get_session_with_current_tenant"),
        patch("ee.onyx.hooks.executor.update_hook__no_commit"),
        patch("ee.onyx.hooks.executor.create_hook_execution_log__no_commit"),
        patch("httpx.Client") as mock_client_cls,
    ):
        mock_client = _setup_client(mock_client_cls, response=_make_response())
        execute_hook(
            db_session=db_session,
            hook_point=HookPoint.QUERY_PROCESSING,
            payload=_PAYLOAD,
            response_type=QueryProcessingResponse,
        )

    _, call_kwargs = mock_client.post.call_args
    if expect_auth_header:
        assert call_kwargs["headers"]["Authorization"] == f"Bearer {api_key_value}"
    else:
        assert "Authorization" not in call_kwargs["headers"]


# ---------------------------------------------------------------------------
# Persist session failure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "http_exception,expect_onyx_error",
    [
        pytest.param(None, False, id="success_path"),
        pytest.param(httpx.ConnectError("refused"), True, id="hard_fail_path"),
    ],
)
def test_persist_session_failure_is_swallowed(
    db_session: MagicMock,
    http_exception: Exception | None,
    expect_onyx_error: bool,
) -> None:
    """DB session failure in _persist_result must not mask the real return value or OnyxError."""
    hook = _make_hook(fail_strategy=HookFailStrategy.HARD)

    with (
        patch("ee.onyx.hooks.executor.MULTI_TENANT", False),
        patch(
            "ee.onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch(
            "ee.onyx.hooks.executor.get_session_with_current_tenant",
            side_effect=RuntimeError("DB unavailable"),
        ),
        patch("httpx.Client") as mock_client_cls,
    ):
        _setup_client(
            mock_client_cls,
            response=_make_response() if not http_exception else None,
            side_effect=http_exception,
        )

        if expect_onyx_error:
            with pytest.raises(OnyxError) as exc_info:
                execute_hook(
                    db_session=db_session,
                    hook_point=HookPoint.QUERY_PROCESSING,
                    payload=_PAYLOAD,
                    response_type=QueryProcessingResponse,
                )
            assert exc_info.value.error_code is OnyxErrorCode.HOOK_EXECUTION_FAILED
        else:
            result = execute_hook(
                db_session=db_session,
                hook_point=HookPoint.QUERY_PROCESSING,
                payload=_PAYLOAD,
                response_type=QueryProcessingResponse,
            )
            assert isinstance(result, QueryProcessingResponse)
            assert result.query == _RESPONSE_PAYLOAD["query"]


# ---------------------------------------------------------------------------
# Response model validation
# ---------------------------------------------------------------------------


class _StrictResponse(BaseModel):
    """Strict model used to reliably trigger a ValidationError in tests."""

    required_field: str  # no default → missing key raises ValidationError


@pytest.mark.parametrize(
    "fail_strategy,expected_type",
    [
        pytest.param(
            HookFailStrategy.SOFT, HookSoftFailed, id="validation_failure_soft"
        ),
        pytest.param(HookFailStrategy.HARD, OnyxError, id="validation_failure_hard"),
    ],
)
def test_response_validation_failure_respects_fail_strategy(
    db_session: MagicMock,
    fail_strategy: HookFailStrategy,
    expected_type: type,
) -> None:
    """A response that fails response_model validation is treated like any other
    hook failure: logged, is_reachable left unchanged, fail_strategy respected."""
    hook = _make_hook(fail_strategy=fail_strategy)

    with (
        patch("ee.onyx.hooks.executor.MULTI_TENANT", False),
        patch(
            "ee.onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("ee.onyx.hooks.executor.get_session_with_current_tenant"),
        patch("ee.onyx.hooks.executor.update_hook__no_commit") as mock_update,
        patch(
            "ee.onyx.hooks.executor.create_hook_execution_log__no_commit"
        ) as mock_log,
        patch("httpx.Client") as mock_client_cls,
    ):
        # Response payload is missing required_field → ValidationError
        _setup_client(mock_client_cls, response=_make_response(json_return={}))

        if expected_type is OnyxError:
            with pytest.raises(OnyxError) as exc_info:
                execute_hook(
                    db_session=db_session,
                    hook_point=HookPoint.QUERY_PROCESSING,
                    payload=_PAYLOAD,
                    response_type=_StrictResponse,
                )
            assert exc_info.value.error_code is OnyxErrorCode.HOOK_EXECUTION_FAILED
        else:
            result = execute_hook(
                db_session=db_session,
                hook_point=HookPoint.QUERY_PROCESSING,
                payload=_PAYLOAD,
                response_type=_StrictResponse,
            )
            assert isinstance(result, HookSoftFailed)

    # is_reachable must not be updated — server responded correctly
    mock_update.assert_not_called()
    # failure must be logged
    mock_log.assert_called_once()
    _, log_kwargs = mock_log.call_args
    assert log_kwargs["is_success"] is False
    assert "validation" in (log_kwargs["error_message"] or "").lower()


# ---------------------------------------------------------------------------
# Outer soft-fail guard in execute_hook
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fail_strategy,expected_type",
    [
        pytest.param(HookFailStrategy.SOFT, HookSoftFailed, id="unexpected_exc_soft"),
        pytest.param(HookFailStrategy.HARD, ValueError, id="unexpected_exc_hard"),
    ],
)
def test_unexpected_exception_in_inner_respects_fail_strategy(
    db_session: MagicMock,
    fail_strategy: HookFailStrategy,
    expected_type: type,
) -> None:
    """An unexpected exception raised by _execute_hook_inner (not an OnyxError from
    HARD fail — e.g. a bug or an assertion error) must be swallowed and return
    HookSoftFailed for SOFT strategy, or re-raised for HARD strategy."""
    hook = _make_hook(fail_strategy=fail_strategy)

    with (
        patch("ee.onyx.hooks.executor.MULTI_TENANT", False),
        patch(
            "ee.onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch(
            "ee.onyx.hooks.executor._execute_hook_inner",
            side_effect=ValueError("unexpected bug"),
        ),
    ):
        if expected_type is HookSoftFailed:
            result = execute_hook(
                db_session=db_session,
                hook_point=HookPoint.QUERY_PROCESSING,
                payload=_PAYLOAD,
                response_type=QueryProcessingResponse,
            )
            assert isinstance(result, HookSoftFailed)
        else:
            with pytest.raises(ValueError, match="unexpected bug"):
                execute_hook(
                    db_session=db_session,
                    hook_point=HookPoint.QUERY_PROCESSING,
                    payload=_PAYLOAD,
                    response_type=QueryProcessingResponse,
                )


def test_is_reachable_failure_does_not_prevent_log(db_session: MagicMock) -> None:
    """is_reachable update failing (e.g. concurrent hook deletion) must not
    prevent the execution log from being written.

    Simulates the production failure path: update_hook__no_commit raises
    OnyxError(NOT_FOUND) as it would if the hook was concurrently deleted
    between the initial lookup and the reachable update.
    """
    hook = _make_hook(fail_strategy=HookFailStrategy.SOFT)

    with (
        patch("ee.onyx.hooks.executor.MULTI_TENANT", False),
        patch(
            "ee.onyx.hooks.executor.get_non_deleted_hook_by_hook_point",
            return_value=hook,
        ),
        patch("ee.onyx.hooks.executor.get_session_with_current_tenant"),
        patch(
            "ee.onyx.hooks.executor.update_hook__no_commit",
            side_effect=OnyxError(OnyxErrorCode.NOT_FOUND, "hook deleted"),
        ),
        patch(
            "ee.onyx.hooks.executor.create_hook_execution_log__no_commit"
        ) as mock_log,
        patch("httpx.Client") as mock_client_cls,
    ):
        _setup_client(mock_client_cls, side_effect=httpx.ConnectError("refused"))
        result = execute_hook(
            db_session=db_session,
            hook_point=HookPoint.QUERY_PROCESSING,
            payload=_PAYLOAD,
            response_type=QueryProcessingResponse,
        )

    assert isinstance(result, HookSoftFailed)
    mock_log.assert_called_once()
