"""The permission-aware side of the Linear connector: the walk that names
who may read each issue. Every line here exists only to sync Linear
permissions, so it lives in EE on top of the Community Edition connector's
indexing, credentials and gateway."""

from typing import Any

from ee.onyx.external_permissions.linear.access import SharedAccessIndex, issue_access
from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import build_db_credentials_provider
from onyx.connectors.factory import build_connector_kwargs
from onyx.connectors.interfaces import (
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnectorWithPermSync,
)
from onyx.connectors.linear.connector import LinearConnector
from onyx.connectors.linear.models import IssueAccess
from onyx.connectors.linear.source_operations import (
    ACCESS_PAGE_SIZE,
    LinearSourceOperations,
)
from onyx.connectors.models import HierarchyNode, SlimDocument
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Every walked issue id stays in memory until the walk ends, with the shares
# that name anyone. Past this many the workspace is worth a look.
_RETAINED_ISSUES_WARNING: int = 250_000


def _beat(callback: IndexingHeartbeatInterface | None, amount: int) -> None:
    """Renews the sync's lease and honours a stop between reads."""
    if callback is None:
        return
    if callback.should_stop():
        raise RuntimeError("Linear permission sync stopped on the heartbeat's signal")
    callback.progress("linear_perm_sync", amount)


def issue_access_by_id(
    ops: LinearSourceOperations, issue_filter: dict[str, Any]
) -> dict[str, ExternalAccess]:
    """Who may read each issue the filter matches, for a targeted reindex.
    Ancestors outside the filter are read on demand for inherited sharing."""
    shares: SharedAccessIndex = SharedAccessIndex(
        lambda issue_id: ops.get_issue_share(issue_id=issue_id)
    )
    issues: list[IssueAccess] = []
    organization_id: str = ""
    for page in ops.iterate_issue_access(issue_filter=issue_filter):
        organization_id = page.organization_id
        for issue in page.issues:
            shares.record(issue.id, issue.share)
            issues.append(issue)
    return {
        issue.id: issue_access(issue.team, organization_id, shares.emails_for(issue.id))
        for issue in issues
    }


class LinearPermSyncConnector(LinearConnector, SlimConnectorWithPermSync):
    """The connector with its permission walk."""

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Every issue the token can read, with who may read it. The doc sync
        makes any indexed issue this does not list private, so the window is
        ignored. A sub-issue that inherits sharing waits for the walk to end,
        since its parent can page after it."""
        ops = self.ops
        shares: SharedAccessIndex = SharedAccessIndex(
            lambda issue_id: ops.get_issue_share(issue_id=issue_id)
        )
        warned: bool = False
        inheriting: list[IssueAccess] = []
        organization_id: str = ""
        for page in ops.iterate_issue_access(issue_filter=self._issue_filter()):
            organization_id = page.organization_id
            docs: list[SlimDocument | HierarchyNode] = []
            for issue in page.issues:
                shares.record(issue.id, issue.share)
                if issue.share.inherits:
                    inheriting.append(issue)
                    continue
                docs.append(
                    SlimDocument(
                        id=issue.id,
                        external_access=issue_access(
                            issue.team, organization_id, issue.share.emails
                        ),
                    )
                )
            yield docs
            _beat(callback, len(page.issues))
            if not warned and len(shares) > _RETAINED_ISSUES_WARNING:
                warned = True
                logger.warning(
                    "Linear permission sync is keeping %s walked issues in memory "
                    "until the walk ends",
                    len(shares),
                )
        # Each inheriting issue can read ancestors outside the scope, so the
        # heartbeat runs per issue rather than per batch.
        batch: list[SlimDocument | HierarchyNode] = []
        for issue in inheriting:
            batch.append(
                SlimDocument(
                    id=issue.id,
                    external_access=issue_access(
                        issue.team, organization_id, shares.emails_for(issue.id)
                    ),
                )
            )
            _beat(callback, 1)
            if len(batch) == ACCESS_PAGE_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def linear_connector(cc_pair: ConnectorCredentialPair) -> LinearPermSyncConnector:
    """The pair's connector on the DB credential provider, whose rotation lock
    and write-back keep a refreshed OAuth token shared with indexing."""
    connector = LinearPermSyncConnector(
        **build_connector_kwargs(
            cc_pair.connector.source, cc_pair.connector.connector_specific_config
        )
    )
    connector.set_credentials_provider(
        build_db_credentials_provider(DocumentSource.LINEAR, cc_pair.credential.id)
    )
    return connector
