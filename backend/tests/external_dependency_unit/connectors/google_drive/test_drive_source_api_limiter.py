"""The shared source-API limiter with the Drive connector, against the mock
Google Drive server and a real Redis.

The mock has a tight project quota. With the limiter set to that quota, the
listing waits for its budget and Google refuses far fewer calls. No file is
lost in the two runs."""

from collections.abc import Iterator
from uuid import uuid4

import pytest

from onyx.background.indexing.source_api_limiter import (
    RedisSourceApiLimiter,
    SourceApiBudget,
)
from onyx.connectors.google_drive import parallel_listing
from onyx.connectors.google_drive.quota import DriveQuotaApi
from onyx.redis.redis_pool import get_redis_client
from tests.external_dependency_unit.connectors.google_drive.conftest import MockDrive
from tests.external_dependency_unit.connectors.google_drive.test_checkpointed_slim_listing import (
    list_with_resume,
)

_CORPUS = {
    "num_users": 3,
    "num_groups": 1,
    "num_shared_drives": 2,
    "files_per_shared_drive": 150,
    "files_per_user": 20,
    "folders_per_container": 2,
    "shortcut_fraction": 0.0,
}
# 20 list calls in each 2 s window.
_WINDOW_SECONDS = 2
_PROJECT_UNITS_PER_MINUTE = 60_000
_UNITS_PER_WINDOW = _PROJECT_UNITS_PER_MINUTE * _WINDOW_SECONDS // 60


@pytest.fixture
def tenant_id() -> Iterator[str]:
    tenant = f"tenant_test_{uuid4().hex[:12]}"
    yield tenant
    client = get_redis_client(tenant_id=tenant)
    for key in client.scan_iter("*"):
        client.delete(key)


def _list(
    mock: MockDrive, limiter: RedisSourceApiLimiter | None
) -> tuple[set[str], int]:
    connector = mock.build_connector()
    if limiter is not None:
        connector.set_source_api_limiter(limiter)
    mock.reset_stats()
    # A folder read that Google refuses fails its call. The call then runs
    # again from its checkpoint, as the next attempt does.
    listing = list_with_resume(connector, retry_failed_calls=True)
    assert listing.failures == []
    assert len(listing.file_ids) == len(set(listing.file_ids))
    return set(listing.file_ids), int(mock.stats()["rate_limited"])


def test_the_limiter_keeps_the_listing_under_the_quota(
    own_mock_drive: MockDrive, tenant_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(parallel_listing, "LISTING_PAGE_SIZE", 10)
    own_mock_drive.set_corpus(_CORPUS)
    expected = own_mock_drive.content_file_ids()
    own_mock_drive.patch_config(
        {
            "quota": {
                "window_seconds": _WINDOW_SECONDS,
                "project_units_per_minute": _PROJECT_UNITS_PER_MINUTE,
                "retry_after_seconds": 1,
            }
        }
    )

    unlimited_ids, unlimited_refusals = _list(own_mock_drive, None)

    limiter = RedisSourceApiLimiter(
        tenant_id,
        "google_drive:test",
        {
            DriveQuotaApi.DRIVE.value: SourceApiBudget(
                # A little under the quota: the two clocks do not line up.
                per_credential=int(_UNITS_PER_WINDOW * 0.8),
                period_seconds=_WINDOW_SECONDS,
            )
        },
    )
    limited_ids, limited_refusals = _list(own_mock_drive, limiter)

    assert unlimited_ids == expected
    assert limited_ids == expected
    assert unlimited_refusals > 10
    assert limited_refusals < unlimited_refusals / 4
