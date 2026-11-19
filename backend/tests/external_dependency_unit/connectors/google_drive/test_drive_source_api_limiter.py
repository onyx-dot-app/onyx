"""The shared source-API limiter with the Drive connector, against the mock
Google Drive server and a real Redis.

The mock has a tight project quota. With the limiter set to that quota, the
listing waits for its budget and Google refuses far fewer calls. No file is
lost in the two runs."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from prometheus_client import REGISTRY

from onyx.configs.constants import DocumentSource
from onyx.connectors.google_drive import parallel_listing, source_operations
from onyx.connectors.google_drive.quota import DriveQuotaApi
from onyx.connectors.google_drive.source_operations import GoogleDriveHttpError
from onyx.connectors.interfaces import SourceApiLimiter
from onyx.connectors.source_api_limiter import (
    RedisSourceApiLimiter,
    SourceApiBudget,
)
from onyx.redis.redis_pool import get_redis_client
from onyx.server.metrics.source_api_metrics import RequestOutcome
from onyx.utils.retry_wrapper import retry_builder
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


def _metric(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _counted_requests(outcome: RequestOutcome | None = None) -> float:
    """The Drive requests that the gateway counted, of every API."""
    outcomes = [outcome] if outcome is not None else list(RequestOutcome)
    return sum(
        _metric(
            "onyx_source_api_requests_total",
            source="google_drive",
            api=api,
            outcome=counted.value,
        )
        for api in ("drive", "docs", "admin")
        for counted in outcomes
    )


def _list(
    mock: MockDrive, limiter: RedisSourceApiLimiter | None
) -> tuple[set[str], int]:
    connector = mock.build_connector()
    if limiter is not None:
        connector.set_source_api_limiter(limiter)
    mock.reset_stats()
    requests_before = _counted_requests()
    refusals_before = _counted_requests(RequestOutcome.RATE_LIMITED)
    # A folder read that Google refuses fails its call. The call then runs
    # again from its checkpoint, as the next attempt does.
    listing = list_with_resume(connector, retry_failed_calls=True)
    assert listing.failures == []
    assert len(listing.file_ids) == len(set(listing.file_ids))
    stats = mock.stats()
    # The request metrics count what Google got, retries included. Token
    # requests are not API requests.
    api_requests = sum(
        op["count"] for name, op in stats["ops"].items() if name != "oauth.token"
    )
    assert _counted_requests() - requests_before == api_requests
    assert (
        _counted_requests(RequestOutcome.RATE_LIMITED) - refusals_before
        == stats["rate_limited"]
    )
    return set(listing.file_ids), int(stats["rate_limited"])


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

    pool_cuts_before = _metric("onyx_adaptive_pool_cuts_total", pool="drive_listing")
    unlimited_ids, unlimited_refusals = _list(own_mock_drive, None)
    # The listing pool answered the refusals with fewer workers.
    assert (
        _metric("onyx_adaptive_pool_cuts_total", pool="drive_listing")
        > pool_cuts_before
    )

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
        source=DocumentSource.GOOGLE_DRIVE,
    )
    waited_before = _metric(
        "onyx_source_api_limiter_wait_seconds_total", source="google_drive", api="drive"
    )
    limited_ids, limited_refusals = _list(own_mock_drive, limiter)
    # The calls waited for the budget, and the gauge shows the budget.
    assert (
        _metric(
            "onyx_source_api_limiter_wait_seconds_total",
            source="google_drive",
            api="drive",
        )
        > waited_before
    )
    assert (
        _metric(
            "onyx_source_api_limiter_budget",
            source="google_drive",
            api="drive",
            scope="project",
        )
        > 0
    )

    assert unlimited_ids == expected
    assert limited_ids == expected
    assert unlimited_refusals > 10
    assert limited_refusals < unlimited_refusals / 4


class _RecordingLimiter(SourceApiLimiter):
    def __init__(self) -> None:
        self.bulk: list[bool] = []
        self.acquired: list[tuple[str, int, str | None, int]] = []
        self.reports: list[tuple[str, str | None, bool, int]] = []

    def acquire(
        self,
        api: str,
        cost: int,
        user: str | None = None,
        request_count: int = 1,
        *,
        bulk: bool = False,
    ) -> None:
        self.bulk.append(bulk)
        self.acquired.append((api, cost, user, request_count))

    def report_rate_limit(
        self, api: str, user: str | None, user_scope: bool, count: int = 1
    ) -> None:
        self.reports.append((api, user, user_scope, count))


def test_a_batch_spends_each_request_and_reports_refused_files(
    own_mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A batch read spends one request for each file in it. Google refuses
    some files of the batch for the project's rate, and the gateway reports
    them in one report with their count. The refused files go again in a new
    batch, which spends for them."""
    # Two tries with no wait.
    monkeypatch.setattr(
        source_operations,
        "_retry_transient_batch_calls",
        retry_builder(
            tries=2,
            delay=0,
            jitter=0,
            exceptions=source_operations._TransientBatchCalls,
        ),
    )
    own_mock_drive.patch_config(
        {
            "quota": {
                "model": "requests",
                "project_requests_per_minute": 5,
                "user_requests_per_minute": 1_000,
            }
        }
    )
    connector = own_mock_drive.build_connector()
    limiter = _RecordingLimiter()
    connector.set_source_api_limiter(limiter)
    admin = own_mock_drive.client.get("/_mock/corpus/summary").json()["admin_email"]
    file_ids = sorted(own_mock_drive.content_file_ids())[:20]

    result = connector.ops.batch_get_files(
        user_email=admin,
        file_ids_by_key={file_id: file_id for file_id in file_ids},
        fields="id",
    )

    batches = [call[3] for call in limiter.acquired]
    assert len(batches) == 2 and batches[0] == len(file_ids)
    # The first report counts the files that the second batch sends again.
    assert limiter.reports[0] == (DriveQuotaApi.DRIVE.value, admin, False, batches[1])
    refused = [
        error
        for error in result.errors.values()
        if isinstance(error, GoogleDriveHttpError) and error.rate_limited
    ]
    # The quota allows 5 a minute: the second batch is refused too.
    assert refused
    assert limiter.reports[1] == (
        DriveQuotaApi.DRIVE.value,
        admin,
        False,
        len(refused),
    )
