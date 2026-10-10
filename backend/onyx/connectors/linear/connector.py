import re
import time
from datetime import datetime, timezone
from typing import Any, cast
from urllib.parse import urlparse

from typing_extensions import override

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    LINEAR_CLIENT_ID,
    LINEAR_CLIENT_SECRET,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_oauth_callback_uri,
    time_str_to_utc,
)
from onyx.connectors.interfaces import (
    CredentialsConnector,
    CredentialsProviderInterface,
    GenerateDocumentsOutput,
    GenerateSlimDocumentOutput,
    LoadConnector,
    NormalizationResult,
    OAuthConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
    SlimConnectorWithPermSync,
)
from onyx.connectors.linear.access import SharedAccessIndex, issue_access
from onyx.connectors.linear.models import IssueAccess
from onyx.connectors.linear.scope import (
    issue_filter,
    missing_projects,
    missing_team_keys,
    normalize_team_keys,
    project_filter,
    project_scope,
    scope_error,
)
from onyx.connectors.linear.source_operations import (
    ACCESS_PAGE_SIZE,
    ACCESS_TOKEN,
    EXPIRE_AT,
    EXPIRES_IN,
    REFRESH_TOKEN,
    LinearSourceOperations,
    is_expiring,
    refresh_oauth_token,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    ImageSection,
    SlimDocument,
    TextSection,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import request_with_retries

logger = setup_logger()

# Every walked issue id stays in memory until the walk ends, with the shares
# that name anyone. Past this many the workspace is worth a look.
_RETAINED_ISSUES_WARNING: int = 250_000


class LinearConnector(
    LoadConnector,
    PollConnector,
    OAuthConnector,
    SlimConnectorWithPermSync,
    CredentialsConnector,
):
    supports_manual_credentials = True

    def __init__(
        self,
        team_keys: list[str] | None = None,
        projects: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.team_keys = normalize_team_keys(team_keys)
        # The entries as configured, for the checks that rerun before a sync.
        self.projects: list[str] = projects or []
        self.project_names, self.project_slug_ids = project_scope(projects)
        self.batch_size = batch_size
        self._ops: LinearSourceOperations | None = None

    @property
    def ops(self) -> LinearSourceOperations:
        if self._ops is None:
            raise ConnectorMissingCredentialError("Linear")
        return self._ops

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Manual credentials. An expiring OAuth token is refreshed here and
        handed back so the caller can store it; the DB provider path refreshes
        inside the gateway instead."""
        refreshed: dict[str, Any] | None = None
        if is_expiring(credentials):
            refreshed = refresh_oauth_token(credentials)
            credentials = refreshed
        self.set_credentials_provider(
            OnyxStaticCredentialsProvider(
                None, DocumentSource.LINEAR.value, credentials
            )
        )
        return refreshed

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self._ops = LinearSourceOperations(credentials_provider=credentials_provider)

    def validate_connector_settings(self) -> None:
        """One message names every missing team and project."""
        missing_teams: list[str] = (
            missing_team_keys(self.ops, self.team_keys) if self.team_keys else []
        )
        missing: list[str] = (
            missing_projects(self.ops, self.project_names, self.project_slug_ids)
            if self.project_names or self.project_slug_ids
            else []
        )
        if missing_teams or missing:
            raise scope_error(missing_teams, missing)

    def _issue_filter(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> dict[str, Any]:
        return issue_filter(
            self.team_keys,
            project_filter(self.project_names, self.project_slug_ids),
            start,
            end,
        )

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

    @classmethod
    def oauth_id(cls) -> DocumentSource:
        return DocumentSource.LINEAR

    @classmethod
    def oauth_authorization_url(
        cls,
        base_domain: str,
        state: str,
        additional_kwargs: dict[str, str],  # noqa: ARG003
        code_challenge: str | None = None,  # noqa: ARG003
    ) -> str:
        if not LINEAR_CLIENT_ID:
            raise ValueError("LINEAR_CLIENT_ID environment variable must be set")

        callback_uri = get_oauth_callback_uri(base_domain, DocumentSource.LINEAR.value)
        return (
            f"https://linear.app/oauth/authorize"
            f"?client_id={LINEAR_CLIENT_ID}"
            f"&redirect_uri={callback_uri}"
            f"&response_type=code"
            f"&scope=read"
            f"&state={state}"
            f"&prompt=consent"  # prompts user for access; allows choosing workspace
        )

    @classmethod
    def oauth_code_to_token(
        cls,
        base_domain: str,
        code: str,
        additional_kwargs: dict[str, str],  # noqa: ARG003
        code_verifier: str | None = None,  # noqa: ARG003
    ) -> dict[str, Any]:
        data = {
            "code": code,
            "redirect_uri": get_oauth_callback_uri(
                base_domain, DocumentSource.LINEAR.value
            ),
            "client_id": LINEAR_CLIENT_ID,
            "client_secret": LINEAR_CLIENT_SECRET,
            "grant_type": "authorization_code",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        response = request_with_retries(
            method="POST",
            url="https://api.linear.app/oauth/token",
            data=data,
            headers=headers,
            backoff=0,
            delay=0.1,
        )
        if not response.ok:
            raise RuntimeError(f"Failed to exchange code for token: {response.text}")

        token_data = response.json()

        expire_at = time.time() + token_data[EXPIRES_IN]

        return {
            ACCESS_TOKEN: token_data[ACCESS_TOKEN],
            EXPIRE_AT: int(expire_at),
            REFRESH_TOKEN: token_data[REFRESH_TOKEN],
        }

    def _process_issues(
        self, start_str: datetime | None = None, end_str: datetime | None = None
    ) -> GenerateDocumentsOutput:
        for nodes in self.ops.iterate_issues(
            issue_filter=self._issue_filter(start_str, end_str),
            page_size=self.batch_size,
        ):
            documents: list[Document | HierarchyNode] = []
            for node in nodes:
                # Create sections for description and comments
                sections = [
                    TextSection(
                        link=node["url"],
                        text=node["description"] or "",
                    )
                ]

                # Add comment sections
                sections.extend(
                    TextSection(
                        link=node["url"],
                        text=comment["body"] or "",
                    )
                    for comment in node["comments"]["nodes"]
                )

                # Cast the sections list to the expected type
                typed_sections = cast(list[TextSection | ImageSection], sections)

                # Extract team name for hierarchy
                team_name = (node.get("team") or {}).get("name") or "Unknown Team"
                identifier = node.get("identifier", node["id"])

                documents.append(
                    Document(
                        id=node["id"],
                        sections=typed_sections,
                        source=DocumentSource.LINEAR,
                        semantic_identifier=f"[{node['identifier']}] {node['title']}",
                        title=node["title"],
                        doc_updated_at=time_str_to_utc(node["updatedAt"]),
                        # NOTE: doc_created_at population not yet verified against live data
                        doc_created_at=time_str_to_utc(node["createdAt"]),
                        doc_metadata={
                            "hierarchy": {
                                "source_path": [team_name],
                                "team_name": team_name,
                                "identifier": identifier,
                            }
                        },
                        metadata={
                            k: str(v)
                            for k, v in {
                                "team": (node.get("team") or {}).get("name"),
                                "project": (node.get("project") or {}).get("name"),
                                "creator": node.get("creator"),
                                "assignee": node.get("assignee"),
                                "state": (node.get("state") or {}).get("name"),
                                "priority": node.get("priority"),
                                "estimate": node.get("estimate"),
                                "started_at": node.get("startedAt"),
                                "completed_at": node.get("completedAt"),
                                "created_at": node.get("createdAt"),
                                "due_date": node.get("dueDate"),
                            }.items()
                            if v is not None
                        },
                    )
                )
            yield documents

    def load_from_state(self) -> GenerateDocumentsOutput:
        yield from self._process_issues()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_time = datetime.fromtimestamp(start, tz=timezone.utc)
        end_time = datetime.fromtimestamp(end, tz=timezone.utc)

        yield from self._process_issues(start_str=start_time, end_str=end_time)

    @classmethod
    @override
    def normalize_url(cls, url: str) -> NormalizationResult:
        """Extract Linear issue identifier from URL.

        Linear URLs are like: https://linear.app/team/issue/IDENTIFIER/...
        Returns the identifier (e.g., "DAN-2327") which can be used to match Document.link.
        """
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()

        if "linear.app" not in netloc:
            return NormalizationResult(normalized_url=None, use_default=False)

        # Extract identifier from path: /team/issue/IDENTIFIER/...
        # Pattern: /{team}/issue/{identifier}/...
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) >= 3 and path_parts[1] == "issue":
            identifier = path_parts[2]
            # Validate identifier format (e.g., "DAN-2327")
            if re.match(r"^[A-Z]+-\d+$", identifier):
                return NormalizationResult(normalized_url=identifier, use_default=False)

        return NormalizationResult(normalized_url=None, use_default=False)
