import pytest
from pydantic import ValidationError

from onyx.db.enums import HookFailStrategy
from onyx.db.enums import HookPoint
from onyx.hooks.models import HookCreateRequest
from onyx.hooks.models import HookUpdateRequest


def test_hook_update_request_rejects_empty() -> None:
    # No fields supplied at all
    with pytest.raises(ValidationError, match="At least one field must be provided"):
        HookUpdateRequest()


def test_hook_update_request_rejects_null_name_when_only_field() -> None:
    # Explicitly setting name=None is rejected as name cannot be cleared
    with pytest.raises(ValidationError, match="name cannot be cleared"):
        HookUpdateRequest(name=None)


def test_hook_update_request_accepts_single_field() -> None:
    req = HookUpdateRequest(name="new name")
    assert req.name == "new name"


def test_hook_update_request_accepts_partial_fields() -> None:
    req = HookUpdateRequest(fail_strategy=HookFailStrategy.SOFT, timeout_seconds=10.0)
    assert req.fail_strategy == HookFailStrategy.SOFT
    assert req.timeout_seconds == 10.0
    assert req.name is None


def test_hook_update_request_rejects_null_name() -> None:
    with pytest.raises(ValidationError, match="name cannot be cleared"):
        HookUpdateRequest(name=None, fail_strategy=HookFailStrategy.SOFT)


def test_hook_update_request_rejects_empty_name() -> None:
    with pytest.raises(ValidationError, match="name cannot be cleared"):
        HookUpdateRequest(name="", fail_strategy=HookFailStrategy.SOFT)


def test_hook_update_request_rejects_null_endpoint_url() -> None:
    with pytest.raises(ValidationError, match="endpoint_url cannot be cleared"):
        HookUpdateRequest(endpoint_url=None, fail_strategy=HookFailStrategy.SOFT)


def test_hook_update_request_rejects_empty_endpoint_url() -> None:
    with pytest.raises(ValidationError, match="endpoint_url cannot be cleared"):
        HookUpdateRequest(endpoint_url="", fail_strategy=HookFailStrategy.SOFT)


def test_hook_update_request_allows_null_api_key() -> None:
    # api_key=null is valid — means "clear the api key"
    req = HookUpdateRequest(api_key=None)
    assert req.api_key is None
    assert "api_key" in req.model_fields_set


def test_hook_update_request_rejects_whitespace_name() -> None:
    with pytest.raises(ValidationError, match="name cannot be cleared"):
        HookUpdateRequest(name="   ", fail_strategy=HookFailStrategy.SOFT)


def test_hook_update_request_rejects_whitespace_endpoint_url() -> None:
    with pytest.raises(ValidationError, match="endpoint_url cannot be cleared"):
        HookUpdateRequest(endpoint_url="   ", fail_strategy=HookFailStrategy.SOFT)


def test_hook_create_request_rejects_whitespace_name() -> None:
    with pytest.raises(ValidationError, match="whitespace-only"):
        HookCreateRequest(
            name="   ",
            hook_point=HookPoint.QUERY_PROCESSING,
            endpoint_url="https://example.com/hook",
        )


def test_hook_create_request_rejects_whitespace_endpoint_url() -> None:
    with pytest.raises(ValidationError, match="whitespace-only"):
        HookCreateRequest(
            name="my hook",
            hook_point=HookPoint.QUERY_PROCESSING,
            endpoint_url="   ",
        )
