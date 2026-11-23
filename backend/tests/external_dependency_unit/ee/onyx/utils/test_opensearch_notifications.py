"""External dependency unit tests for the OpenSearch cluster issue notifications.

The cluster read is replaced; notifications go to the real PostgreSQL database
and the issue state to the real shared cache.
"""

from collections.abc import Callable, Generator
from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.utils import opensearch_notifications
from ee.onyx.utils.opensearch_notifications import (
    LEASE_KEY,
    SERVICE_STATUS_LINK,
    STATE_KEY,
    notify_admins_of_cluster_issues,
)
from onyx.cache.factory import get_shared_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.configs.constants import NotificationType
from onyx.db.enums import NotificationSeverity
from onyx.db.models import Notification, User
from onyx.db.notification import delete_notifications_by_type
from onyx.document_index.opensearch.models import (
    ClusterIssue,
    ClusterIssueKind,
    ClusterIssueSeverity,
    ClusterNodeStatus,
    ClusterStatus,
    UsageThresholds,
)
from onyx.server.settings.models import Tier
from tests.external_dependency_unit.conftest import MakeTestUser


def _node(name: str) -> ClusterNodeStatus:
    return ClusterNodeStatus(
        node_id=name,
        name=name,
        shard_count=16,
        memory_bytes=64 * 1024**3,
        file_cache_bytes=31 * 1024**3,
        vector_bytes=80 * 1024**3,
        heap_max_bytes=32 * 1024**3,
        heap_used_bytes=8 * 1024**3,
        disk_total_bytes=500 * 1024**3,
        disk_used_bytes=90 * 1024**3,
        cpu_percent=5,
        load_average_1m=0.5,
        search_queue=0,
        search_rejected=0,
    )


def _status(*issues: ClusterIssue) -> ClusterStatus:
    return ClusterStatus(
        checked_at=datetime.now(timezone.utc),
        version="3.6",
        health="green",
        data_node_count=1,
        primary_shards=1,
        active_shards=1,
        unassigned_shards=0,
        nodes=[],
        indexes=[],
        issues=list(issues),
        thresholds=UsageThresholds(
            disk_warning_percent=75,
            disk_critical_percent=85,
            vector_warning_percent=90,
            vector_critical_percent=100,
        ),
    )


RED = ClusterIssue(
    kind=ClusterIssueKind.CLUSTER_RED, severity=ClusterIssueSeverity.CRITICAL, value=3
)
DISK_CRITICAL = ClusterIssue(
    kind=ClusterIssueKind.DISK,
    severity=ClusterIssueSeverity.CRITICAL,
    node_names=["node-2"],
    value=91,
)
DISK_WARNING = ClusterIssue(
    kind=ClusterIssueKind.DISK,
    severity=ClusterIssueSeverity.WARNING,
    node_names=["node-1"],
    value=78,
)


@pytest.fixture
def cluster(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> Generator[list[ClusterStatus | None]]:
    """The reads the next checks return, in order; None means unreachable.

    The notifier tells every active admin in the shared database, so the
    teardown deletes this type's notifications.
    """
    reads: list[ClusterStatus | None] = []

    def read(_: object) -> ClusterStatus:
        status: ClusterStatus | None = reads.pop(0)
        if status is None:
            raise ConnectionError("OpenSearch did not answer")
        return status

    monkeypatch.setattr(opensearch_notifications, "MULTI_TENANT", False)
    monkeypatch.setattr(opensearch_notifications, "DISABLE_VECTOR_DB", False)
    monkeypatch.setattr(opensearch_notifications, "get_tier", lambda: Tier.BUSINESS)
    monkeypatch.setattr(opensearch_notifications, "onyx_index_refs", lambda _: [])
    monkeypatch.setattr(opensearch_notifications, "collect_cluster_status", read)
    cache = get_shared_cache_backend()
    cache.delete(STATE_KEY)
    yield reads
    cache.delete(STATE_KEY)
    cache.delete(LEASE_KEY)
    delete_notifications_by_type(NotificationType.OPENSEARCH_CLUSTER_ISSUE, db_session)


def _check() -> None:
    """Runs one scheduled check; the lease only stops duplicate runs."""
    get_shared_cache_backend().delete(LEASE_KEY)
    notify_admins_of_cluster_issues()


def _notifications(db_session: Session, user_id: UUID) -> list[Notification]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.notif_type == NotificationType.OPENSEARCH_CLUSTER_ISSUE,
            )
            .order_by(Notification.id)
        ).all()
    )


@pytest.fixture
def make_user(
    make_test_user: MakeTestUser,
    tenant_context: None,  # noqa: ARG001
) -> Callable[[str, bool], User]:
    """Users that the teardown deletes, so later checks do not tell them."""

    def make(name: str, is_admin: bool) -> User:
        return make_test_user(name, is_admin=is_admin)

    return make


def test_red_cluster_notifies_admins_once(
    db_session: Session,
    cluster: list[ClusterStatus | None],
    make_user: Callable[[str, bool], User],
) -> None:
    admin = make_user("os_notif_admin", True)
    basic = make_user("os_notif_basic", False)
    cluster.extend([_status(RED), _status(RED)])
    _check()
    _check()

    [notification] = _notifications(db_session, admin.id)
    assert notification.severity == NotificationSeverity.ERROR
    assert notification.title == "The OpenSearch cluster is red"
    assert notification.additional_data is not None
    assert notification.additional_data["link"] == SERVICE_STATUS_LINK
    assert not notification.dismissed
    # Only full admins can open the page, so only they hear about it.
    assert _notifications(db_session, basic.id) == []


def test_sustained_issue_waits_for_a_second_check(
    db_session: Session,
    cluster: list[ClusterStatus | None],
    make_user: Callable[[str, bool], User],
) -> None:
    admin = make_user("os_notif_disk_admin", True)
    cluster.extend([_status(DISK_CRITICAL), _status(DISK_CRITICAL)])
    _check()
    assert _notifications(db_session, admin.id) == []
    _check()
    [notification] = _notifications(db_session, admin.id)
    assert notification.title == "OpenSearch disk at 91% on node-2"


def test_cleared_issue_is_dismissed_and_a_return_notifies_again(
    db_session: Session,
    cluster: list[ClusterStatus | None],
    make_user: Callable[[str, bool], User],
) -> None:
    admin = make_user("os_notif_return_admin", True)
    cluster.extend([_status(RED), _status(), _status(RED)])
    _check()
    _check()
    [cleared] = _notifications(db_session, admin.id)
    assert cleared.dismissed
    _check()
    first, returned = _notifications(db_session, admin.id)
    assert first.dismissed
    assert not returned.dismissed


def test_unreachable_cluster_notifies_after_two_checks(
    db_session: Session,
    cluster: list[ClusterStatus | None],
    make_user: Callable[[str, bool], User],
) -> None:
    admin = make_user("os_notif_down_admin", True)
    cluster.extend([None, None])
    _check()
    assert _notifications(db_session, admin.id) == []
    _check()
    [notification] = _notifications(db_session, admin.id)
    assert notification.title == "OpenSearch is not reachable"


def test_warnings_and_community_tier_do_not_notify(
    db_session: Session,
    cluster: list[ClusterStatus | None],
    make_user: Callable[[str, bool], User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = make_user("os_notif_quiet_admin", True)
    cluster.extend([_status(DISK_WARNING), _status(DISK_WARNING)])
    _check()
    _check()
    assert _notifications(db_session, admin.id) == []

    # The page needs the Business tier, so a Community deployment is not told.
    monkeypatch.setattr(opensearch_notifications, "get_tier", lambda: Tier.COMMUNITY)
    cluster.extend([_status(RED)])
    _check()
    assert _notifications(db_session, admin.id) == []


def test_a_failed_read_keeps_known_alerts_open(
    db_session: Session,
    cluster: list[ClusterStatus | None],
    make_user: Callable[[str, bool], User],
) -> None:
    admin = make_user("os_notif_timeout_admin", True)
    # Disk is told after two checks; a timeout does not clear it or restart its
    # wait, and red health is not told again for the same incident.
    cluster.extend(
        [
            _status(DISK_CRITICAL, RED),
            _status(DISK_CRITICAL, RED),
            None,
            _status(DISK_CRITICAL, RED),
        ]
    )
    for _ in range(4):
        _check()
    open_titles = [
        n.title for n in _notifications(db_session, admin.id) if not n.dismissed
    ]
    assert sorted(open_titles) == [
        "OpenSearch disk at 91% on node-2",
        "The OpenSearch cluster is red",
    ]
    assert len(_notifications(db_session, admin.id)) == 2


def test_lost_state_still_clears_and_does_not_repeat(
    db_session: Session,
    cluster: list[ClusterStatus | None],
    make_user: Callable[[str, bool], User],
) -> None:
    admin = make_user("os_notif_lost_admin", True)
    cluster.extend([_status(RED), _status(RED), _status()])
    _check()
    # The cache is lost while the cluster stays red: no second notification.
    get_shared_cache_backend().delete(STATE_KEY)
    _check()
    [red] = _notifications(db_session, admin.id)
    assert not red.dismissed
    # Lost again, then healthy: the open banner is still cleared.
    get_shared_cache_backend().delete(STATE_KEY)
    _check()
    [red] = _notifications(db_session, admin.id)
    assert red.dismissed


def test_a_failed_dismissal_is_retried_on_the_next_check(
    db_session: Session,
    cluster: list[ClusterStatus | None],
    make_user: Callable[[str, bool], User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = make_user("os_notif_retry_admin", True)
    cluster.extend([_status(RED), _status(), _status()])
    _check()

    def fail(*_args: object) -> None:
        raise RuntimeError("database unavailable")

    real_dismiss = opensearch_notifications.dismiss_notifications_by_additional_data
    monkeypatch.setattr(
        opensearch_notifications, "dismiss_notifications_by_additional_data", fail
    )
    with pytest.raises(RuntimeError):
        _check()
    [red] = _notifications(db_session, admin.id)
    assert not red.dismissed
    # The next healthy check still finds the open banner and clears it.
    monkeypatch.setattr(
        opensearch_notifications,
        "dismiss_notifications_by_additional_data",
        real_dismiss,
    )
    _check()
    [red] = _notifications(db_session, admin.id)
    assert red.dismissed


def test_a_failed_state_save_does_not_hide_a_returning_issue(
    db_session: Session,
    cluster: list[ClusterStatus | None],
    make_user: Callable[[str, bool], User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = make_user("os_notif_save_admin", True)
    cluster.extend([_status(RED), _status(), _status(RED)])
    _check()

    cache_class = type(get_shared_cache_backend())
    real_set = cache_class.set

    def failing_set(
        self: CacheBackend,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,
    ) -> None:
        if key == STATE_KEY:
            raise ConnectionError("cache unavailable")
        real_set(self, key, value, ex)

    monkeypatch.setattr(cache_class, "set", failing_set)
    # The cluster recovers, but the state cannot be saved: nothing is dismissed.
    with pytest.raises(ConnectionError):
        _check()
    monkeypatch.setattr(cache_class, "set", real_set)
    # Red is back, and an admin still has an open alert for it.
    _check()
    assert [n for n in _notifications(db_session, admin.id) if not n.dismissed]


def test_a_generated_node_name_reads_as_node_n(
    db_session: Session,
    cluster: list[ClusterStatus | None],
    make_user: Callable[[str, bool], User],
) -> None:
    admin = make_user("os_notif_name_admin", True)
    hashed = "a4466f7b0edf0e6800cf889f7a538424"
    status = _status(
        ClusterIssue(
            kind=ClusterIssueKind.VECTOR_MEMORY,
            severity=ClusterIssueSeverity.CRITICAL,
            node_names=[hashed],
            value=260,
        )
    )
    status.nodes = [_node(hashed)]
    cluster.extend([status, status])
    _check()
    _check()
    # The page shows the same node as "Node 1".
    [notification] = _notifications(db_session, admin.id)
    assert notification.title == "Vector memory at 260% on Node 1"
