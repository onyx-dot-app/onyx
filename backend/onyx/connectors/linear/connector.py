import re
import time
from collections.abc import Callable, Generator
from datetime import datetime, timezone
from typing import Any, cast
from urllib.parse import urlparse
from uuid import UUID

from more_itertools import chunked
from typing_extensions import override

from onyx.access.models import ExternalAccess
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
    LoadConnector,
    NormalizationResult,
    OAuthConnector,
    PollConnector,
    Resolver,
    SecondsSinceUnixEpoch,
)
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
    ACCESS_TOKEN,
    EXPIRE_AT,
    EXPIRES_IN,
    REFRESH_TOKEN,
    LinearAuthError,
    LinearSourceOperations,
    is_expiring,
    refresh_oauth_token,
)
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    HierarchyNode,
    ImageSection,
    TextSection,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import request_with_retries
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
    noop_fallback,
)

logger = setup_logger()


def _issue_to_document(node: dict[str, Any]) -> Document:
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

    return Document(
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


def _issue_access_by_id(
    ops: LinearSourceOperations, issue_filter: dict[str, Any]
) -> dict[str, ExternalAccess] | None:
    """Who may read each issue the filter matches, as the permission sync
    names it. None without Enterprise Edition."""
    fetch_access = cast(
        Callable[
            [LinearSourceOperations, dict[str, Any]], dict[str, ExternalAccess] | None
        ],
        fetch_versioned_implementation_with_fallback(
            "onyx.external_permissions.linear.connector",
            "issue_access_by_id",
            fallback=noop_fallback,
        ),
    )
    return fetch_access(ops, issue_filter)


def _is_issue_id(document_id: str) -> bool:
    """A Linear issue document id is the issue's UUID."""
    try:
        UUID(document_id)
    except ValueError:
        return False
    return True


def _reindex_failure(
    document_id: str, message: str, e: Exception | None = None
) -> ConnectorFailure:
    return ConnectorFailure(
        failed_document=DocumentFailure(document_id=document_id),
        failure_message=message,
        exception=e,
    )


class LinearConnector(
    LoadConnector, PollConnector, OAuthConnector, CredentialsConnector, Resolver
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
            documents: list[Document | HierarchyNode] = [
                _issue_to_document(node) for node in nodes
            ]
            yield documents

    def load_from_state(self) -> GenerateDocumentsOutput:
        yield from self._process_issues()

    @override
    def reindex(
        self,
        errors: list[ConnectorFailure],
        include_permissions: bool = False,
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        """Reads the failed issues again by id, a batch per query, inside the
        configured teams and projects. The crawl yields no hierarchy nodes, so
        neither does this."""
        issue_ids: list[str] = []
        for error in errors:
            if error.failed_document is None:
                continue
            document_id = error.failed_document.document_id
            if not _is_issue_id(document_id):
                yield _reindex_failure(
                    document_id,
                    f"'{document_id}' is not a Linear issue id, so there is no "
                    "issue to reindex",
                )
                continue
            issue_ids.append(document_id)

        for batch in chunked(dict.fromkeys(issue_ids), self.batch_size):
            yield from self._reindex_batch(batch, include_permissions)

    def _reindex_batch(
        self, issue_ids: list[str], include_permissions: bool
    ) -> Generator[Document | ConnectorFailure, None, None]:
        batch_filter: dict[str, Any] = {
            **self._issue_filter(),
            "id": {"in": issue_ids},
        }
        try:
            nodes: list[dict[str, Any]] = [
                node
                for page in self.ops.iterate_issues(
                    issue_filter=batch_filter, page_size=self.batch_size
                )
                for node in page
            ]
            access: dict[str, ExternalAccess] | None = (
                _issue_access_by_id(self.ops, batch_filter)
                if include_permissions and nodes
                else None
            )
        except (LinearAuthError, ConnectorMissingCredentialError):
            raise
        except Exception as e:
            # One failed query must not cost the other batches their retry.
            logger.exception("Failed to reindex Linear issues %s", issue_ids)
            for issue_id in issue_ids:
                yield _reindex_failure(
                    issue_id, f"Failed to reindex Linear issue {issue_id}: {e}", e
                )
            return

        found: set[str] = set()
        for node in nodes:
            issue_id: str = node["id"]
            found.add(issue_id)
            try:
                document = _issue_to_document(node)
            except Exception as e:
                logger.exception("Failed to convert Linear issue %s", issue_id)
                yield _reindex_failure(
                    issue_id, f"Failed to convert Linear issue {issue_id}: {e}", e
                )
                continue
            if access is not None:
                if issue_id not in access:
                    yield _reindex_failure(
                        issue_id,
                        f"Linear returned no access for issue {issue_id}",
                    )
                    continue
                document.external_access = access[issue_id]
            yield document

        for issue_id in issue_ids:
            if issue_id not in found:
                yield _reindex_failure(
                    issue_id,
                    f"Linear returned no issue {issue_id}: it was deleted, is "
                    "outside the configured teams and projects, or the token "
                    "cannot read it",
                )

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
