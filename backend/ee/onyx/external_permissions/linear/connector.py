"""The permission-aware side of the Linear connector: the walk that names
who may read each issue. Every line here exists only to sync Linear
permissions, so it lives in EE on top of the Community Edition connector's
indexing, credentials and gateway."""

from ee.onyx.external_permissions.linear.access import SharedAccessIndex, issue_access
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
from onyx.connectors.linear.source_operations import ACCESS_PAGE_SIZE
from onyx.connectors.models import HierarchyNode, SlimDocument
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Every walked issue id stays in memory until the walk ends, with the shares
# that name anyone. Past this many the workspace is worth a look.
_RETAINED_ISSUES_WARNING: int = 250_000


class LinearPermSyncConnector(LinearConnector, SlimConnectorWithPermSync):
    """The connector with its permission walk."""

    @classmethod
    def from_connector(cls, connector: LinearConnector) -> "LinearPermSyncConnector":
        """The twin of a connector the factory built, on the same credential
        provider."""
        twin = cls(
            team_keys=connector.team_keys,
            projects=connector.projects,
            batch_size=connector.batch_size,
        )
        twin.set_credentials_provider(connector.ops.credentials_provider)
        return twin

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
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
            if not warned and len(shares) > _RETAINED_ISSUES_WARNING:
                warned = True
                logger.warning(
                    "Linear permission sync is keeping %s walked issues in memory "
                    "until the walk ends",
                    len(shares),
                )
        for start_index in range(0, len(inheriting), ACCESS_PAGE_SIZE):
            yield [
                SlimDocument(
                    id=issue.id,
                    external_access=issue_access(
                        issue.team, organization_id, shares.emails_for(issue.id)
                    ),
                )
                for issue in inheriting[start_index : start_index + ACCESS_PAGE_SIZE]
            ]


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
