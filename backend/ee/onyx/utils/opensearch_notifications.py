"""Notifies full admins of critical OpenSearch cluster issues.

The OpenSearch monitoring task calls notify_admins_of_cluster_issues every
few minutes. It reads the cluster with the same rules as the Service Status
page and sends each critical issue to every active full admin once, as an
ERROR notification (bell and banner) that links to the page. When the issue
clears, its notifications are dismissed; if it comes back, it notifies again.
Warnings stay on the page.
"""

from datetime import datetime, timezone

from pydantic import BaseModel

from ee.onyx.utils.tier import get_tier
from onyx.cache.factory import get_shared_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import NotificationType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import NotificationSeverity
from onyx.db.notification import (
    batch_create_notifications,
    dismiss_notifications_with_value,
)
from onyx.db.users import get_active_admin_users
from onyx.document_index.opensearch.cluster_status import (
    collect_cluster_status,
    onyx_index_refs,
)
from onyx.document_index.opensearch.constants import RESOURCE_CHECK_INTERVAL_SECONDS
from onyx.document_index.opensearch.models import (
    ClusterIssue,
    ClusterIssueKind,
    ClusterIssueSeverity,
    ClusterStatus,
)
from onyx.server.settings.models import Tier
from onyx.server.settings.tier_order import tier_at_least
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

SERVICE_STATUS_LINK = "/admin/service-status"
STATE_KEY = "opensearch_cluster_issue_state"
LEASE_KEY = "opensearch_cluster_issue_lease"
# Long enough to outlive a few skipped checks; a stale state only delays a
# sustained issue by one check.
STATE_TTL_SECONDS = 24 * 60 * 60
# Not reached by a check: OpenSearch did not answer at all.
UNREACHABLE = "unreachable"
# Search is broken now, so the first check that sees these notifies.
IMMEDIATE: frozenset[str] = frozenset(
    {ClusterIssueKind.CLUSTER_RED.value, ClusterIssueKind.INDEX_MISSING.value}
)
# One slow or partial read can show these, so two checks in a row must.
SUSTAINED: frozenset[str] = frozenset(
    {
        ClusterIssueKind.NODES_UNANSWERED.value,
        ClusterIssueKind.DISK.value,
        ClusterIssueKind.VECTOR_MEMORY.value,
        UNREACHABLE,
    }
)


class IssueState(BaseModel):
    # When each critical issue was first seen, by kind; an issue that clears
    # leaves the map, so its return is a new occurrence.
    first_seen: dict[str, datetime] = {}


def _copy(kind: str, issue: ClusterIssue | None) -> tuple[str, str]:
    """The notification's title and description."""
    nodes: str = ", ".join(issue.node_names) if issue else ""
    value: int = round(issue.value) if issue else 0
    if kind == ClusterIssueKind.CLUSTER_RED.value:
        return (
            "The OpenSearch cluster is red",
            "Some primary shards are not assigned, so part of the index cannot "
            "be searched. Check the OpenSearch logs.",
        )
    if kind == ClusterIssueKind.INDEX_MISSING.value:
        return (
            "The search index is missing",
            "OpenSearch has no index for the current search settings, so search "
            "returns nothing.",
        )
    if kind == ClusterIssueKind.NODES_UNANSWERED.value:
        return (
            f"{value} OpenSearch data node(s) did not answer",
            "Check that every data node is running.",
        )
    if kind == ClusterIssueKind.DISK.value:
        return (
            f"OpenSearch disk at {value}% on {nodes}",
            "OpenSearch stops placing shards on a data node at 85%. Add storage "
            "or data nodes.",
        )
    if kind == ClusterIssueKind.VECTOR_MEMORY.value:
        return (
            f"Vector memory at {value}% on {nodes}",
            "The vectors do not fit in memory, so search reads them from disk. "
            "Add memory or data nodes, or use a smaller vector quantization.",
        )
    return (
        "OpenSearch is not reachable",
        "The search cluster did not answer two checks in a row, so search can fail.",
    )


def _read_state(cache: CacheBackend) -> IssueState:
    raw: bytes | None = cache.get(STATE_KEY)
    return IssueState.model_validate_json(raw) if raw else IssueState()


def notify_admins_of_cluster_issues() -> None:
    """Sends new critical cluster issues to full admins and dismisses cleared
    ones. Only for self-hosted deployments on the Business tier or above, the
    ones that can open the Service Status page."""
    if MULTI_TENANT or DISABLE_VECTOR_DB:
        return
    if not tier_at_least(get_tier(), Tier.BUSINESS):
        return
    cache: CacheBackend = get_shared_cache_backend()
    # Half the interval: a retried task skips, the next scheduled one runs.
    if not cache.set_if_absent(LEASE_KEY, "1", ex=RESOURCE_CHECK_INTERVAL_SECONDS // 2):
        return

    now: datetime = datetime.now(timezone.utc)
    with get_session_with_current_tenant() as db_session:
        current: dict[str, ClusterIssue | None]
        try:
            status: ClusterStatus = collect_cluster_status(onyx_index_refs(db_session))
            current = {
                issue.kind.value: issue
                for issue in status.issues
                if issue.severity == ClusterIssueSeverity.CRITICAL
                and issue.kind.value in IMMEDIATE | SUSTAINED
            }
        except Exception:
            logger.exception("Unable to read the OpenSearch cluster for notifications")
            current = {UNREACHABLE: None}

        previous: IssueState = _read_state(cache)
        state = IssueState(
            first_seen={kind: previous.first_seen.get(kind, now) for kind in current}
        )
        cache.set(STATE_KEY, state.model_dump_json(), ex=STATE_TTL_SECONDS)

        for kind in previous.first_seen.keys() - current.keys():
            dismiss_notifications_with_value(
                NotificationType.OPENSEARCH_CLUSTER_ISSUE, "issue", kind, db_session
            )
        db_session.commit()

        admin_ids = [admin.id for admin in get_active_admin_users(db_session)]
        for kind, issue in current.items():
            if kind in SUSTAINED and kind not in previous.first_seen:
                continue
            title, description = _copy(kind, issue)
            # One row per admin and occurrence: a returning issue has a new
            # first_seen, so it notifies again.
            batch_create_notifications(
                user_ids=admin_ids,
                notif_type=NotificationType.OPENSEARCH_CLUSTER_ISSUE,
                db_session=db_session,
                title=title,
                description=description,
                additional_data={
                    "issue": kind,
                    "since": state.first_seen[kind].isoformat(),
                    "link": SERVICE_STATUS_LINK,
                },
                severity=NotificationSeverity.ERROR,
            )
