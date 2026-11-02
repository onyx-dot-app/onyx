from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from onyx.server.features.build.sandbox.locks import sandbox_provision_lock
from onyx.server.features.build.sandbox.models import SandboxProvisionContentionError


@pytest.mark.parametrize("failure_at", ["owned", "release"])
def test_release_failure_preserves_successful_result(
    failure_at: str, runtime_lock_cache: MagicMock
) -> None:
    lock = runtime_lock_cache.lock.return_value
    if failure_at == "owned":
        lock.owned.side_effect = RedisError("Cache unavailable")
    else:
        lock.release.side_effect = RedisError("Cache unavailable")

    def provision() -> str:
        with sandbox_provision_lock(uuid4(), "tenant-a"):
            return "ready"

    assert provision() == "ready"


@pytest.mark.parametrize("failure_at", ["owned", "release"])
def test_release_failure_preserves_original_body_error(
    failure_at: str, runtime_lock_cache: MagicMock
) -> None:
    lock = runtime_lock_cache.lock.return_value
    if failure_at == "owned":
        lock.owned.side_effect = RedisError("Cache unavailable")
    else:
        lock.release.side_effect = RedisError("Cache unavailable")
    body_error = ValueError("Provisioning failed")
    with pytest.raises(ValueError) as raised:
        with sandbox_provision_lock(uuid4(), "tenant-a"):
            raise body_error
    assert raised.value is body_error


def test_acquisition_failure_stops_guarded_work(runtime_lock_cache: MagicMock) -> None:
    lock = runtime_lock_cache.lock.return_value
    acquisition_error = RedisError("Cache unavailable")
    lock.acquire.side_effect = acquisition_error
    entered = False
    with pytest.raises(RedisError) as raised:
        with sandbox_provision_lock(uuid4(), "tenant-a"):
            entered = True
    assert raised.value is acquisition_error
    assert not entered


def test_contended_lock_stops_guarded_work(runtime_lock_cache: MagicMock) -> None:
    runtime_lock_cache.lock.return_value.acquire.return_value = False
    entered = False
    with pytest.raises(SandboxProvisionContentionError):
        with sandbox_provision_lock(uuid4(), "tenant-a"):
            entered = True
    assert not entered
