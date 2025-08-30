from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import TYPE_CHECKING

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.bitbucket.utils import build_auth_client
from onyx.connectors.bitbucket.utils import list_repositories
from onyx.connectors.bitbucket.utils import map_pr_to_document
from onyx.connectors.bitbucket.utils import paginate
from onyx.connectors.bitbucket.utils import PR_LIST_RESPONSE_FIELDS
from onyx.connectors.bitbucket.utils import SLIM_PR_LIST_RESPONSE_FIELDS
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    import httpx

logger = setup_logger()


class BitbucketConnector(LoadConnector, PollConnector, SlimConnector):
    """Connector for indexing Bitbucket Cloud pull requests.

    Args:
        workspace: Bitbucket workspace ID.
        repositories: Comma-separated list of repository slugs to index.
        projects: Comma-separated list of project keys to index all repositories within.
        batch_size: Max number of documents to yield per batch.
        prune_closed_prs_after_days: Number of days after which to prune closed PRs.
            Use -1 to disable pruning, 0 to prune immediately, or a positive number
            to prune closed PRs, that are inactive for more than N days.
    """

    def __init__(
        self,
        workspace: str,
        repositories: str | None = None,
        projects: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        prune_closed_prs_after_days: int | None = None,
    ) -> None:
        self.workspace = workspace
        self._repositories = (
            [s.strip() for s in repositories.split(",") if s.strip()]
            if repositories
            else None
        )
        self._projects = (
            [s.strip() for s in projects.split(",") if s.strip()] if projects else None
        )
        self.batch_size = batch_size
        # Pruning config: -1 => never; 0 => immediate; >0 => older than N days
        self._prune_days = (
            prune_closed_prs_after_days
            if prune_closed_prs_after_days is not None
            else -1
        )
        self.email: str | None = None
        self.api_token: str | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load API token-based credentials.

        Expects a dict with keys: `email`, `api_token`.
        """
        self.email = credentials.get("email")
        self.api_token = credentials.get("api_token")
        if not self.email or not self.api_token:
            raise ConnectorMissingCredentialError("Bitbucket")
        return None

    def _client(self) -> httpx.Client:
        """Build an authenticated HTTP client or raise if credentials missing."""
        if not self.email or not self.api_token:
            raise ConnectorMissingCredentialError("Bitbucket")
        return build_auth_client(self.email, self.api_token)

    def _iter_pull_requests_for_repo(
        self, repo_slug: str, params: dict[str, Any] | None = None
    ) -> Iterator[dict[str, Any]]:
        base = f"https://api.bitbucket.org/2.0/repositories/{self.workspace}/{repo_slug}/pullrequests"
        with self._client() as client:
            yield from paginate(client, base, params)

    def _build_params(
        self,
        fields: str = PR_LIST_RESPONSE_FIELDS,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> dict[str, Any] | None:
        """Build Bitbucket fetch params honoring pruning and optional time window.

        Respects start/end if BOTH are provided.
        - prune_days == -1: include OPEN/MERGED/DECLINED; apply start/end to all states if provided.
        - prune_days == 0: include only OPEN; apply start/end to OPEN if provided.
        - prune_days  > 0: include OPEN (with optional start/end);
          for MERGED/DECLINED require updated_on >= max(threshold, start) and <= end (if provided).
        """
        base: dict[str, Any] = {"fields": fields, "pagelen": self.batch_size}

        # Compute common time bounds
        start_iso = (
            datetime.fromtimestamp(start, tz=timezone.utc).isoformat()
            if start is not None
            else None
        )
        end_iso = (
            datetime.fromtimestamp(end, tz=timezone.utc).isoformat()
            if end is not None
            else None
        )

        def _tc(lower: str | None, upper: str | None) -> str | None:
            if lower and upper:
                return f'(updated_on >= "{lower}" AND updated_on <= "{upper}")'
            return None

        params = base
        if self._prune_days == -1:
            # All states, optional global window
            time_clause = _tc(start_iso, end_iso)
            params["state"] = ["OPEN", "MERGED", "DECLINED"]
            q = '(state = "OPEN" OR state = "MERGED" OR state = "DECLINED")'
            if time_clause:
                q = f"{q} AND {time_clause}"
            params["q"] = q

        elif self._prune_days == 0:
            # Only OPEN, optional window
            params["state"] = ["OPEN"]
            open_tc = _tc(start_iso, end_iso)
            q = '(state = "OPEN")'
            if open_tc:
                q = f"{q} AND {open_tc}"
            params["q"] = q

        else:
            # prune_days > 0
            # load all OPEN and MERGED/DECLINED within the adjusted interval
            threshold_dt = datetime.now(tz=timezone.utc) - timedelta(
                days=self._prune_days
            )
            threshold_iso = threshold_dt.isoformat()
            closed_lower_iso = threshold_iso
            if start_iso is not None and start_iso > threshold_iso:
                closed_lower_iso = start_iso
            closed_tc = _tc(closed_lower_iso, end_iso)
            open_tc = _tc(start_iso, end_iso)

            parts: list[str] = []
            if open_tc:
                parts.append(f'(state = "OPEN" AND {open_tc})')
            else:
                parts.append('(state = "OPEN")')
            if closed_tc:
                parts.append(
                    f'((state = "MERGED" OR state = "DECLINED") AND {closed_tc})'
                )
            else:
                parts.append(
                    f'((state = "MERGED" OR state = "DECLINED") AND updated_on >= "{threshold_iso}")'
                )

            q = " OR ".join(parts)
            params["state"] = ["OPEN", "MERGED", "DECLINED"]
            params["q"] = q

        return params

    def _iter_target_repositories(self) -> Iterator[str]:
        """Yield repository slugs based on configuration.

        Priority:
        - repositories list
        - projects list (list repos by project key)
        - workspace (all repos)
        """
        if self._repositories:
            for slug in self._repositories:
                yield slug
            return
        with self._client() as client:
            if self._projects:
                for project_key in self._projects:
                    try:
                        for repo in list_repositories(
                            client, self.workspace, project_key
                        ):
                            slug_val = repo.get("slug")
                            if isinstance(slug_val, str) and slug_val:
                                yield slug_val
                    except Exception as e:
                        logger.error(
                            f"Failed to list repositories for project '{project_key}' in workspace '{self.workspace}'",
                            exc_info=e,
                        )
                return
            try:
                for repo in list_repositories(client, self.workspace, None):
                    slug_val = repo.get("slug")
                    if isinstance(slug_val, str) and slug_val:
                        yield slug_val
            except Exception as e:
                logger.error(
                    f"Failed to list repositories for workspace '{self.workspace}'",
                    exc_info=e,
                )

    def _load_by_params(
        self, params: dict[str, Any] | None = None
    ) -> GenerateDocumentsOutput:
        batch: list[Document] = []
        for slug in self._iter_target_repositories():
            try:
                for pr in self._iter_pull_requests_for_repo(slug, params=params):
                    try:
                        batch.append(map_pr_to_document(pr, self.workspace, slug))
                        if len(batch) >= self.batch_size:
                            yield batch
                            batch = []
                    except Exception as e:
                        logger.error(
                            f"Failed to map PR in repo '{slug}' to document. Skipping PR.",
                            exc_info=e,
                        )
            except Exception as e:
                logger.error(
                    f"Failed to fetch PRs for repository '{slug}'. Continuing with next repo.",
                    exc_info=e,
                )
        if batch:
            yield batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Fetch and yield all pull requests as Documents in batches."""
        params = self._build_params()
        yield from self._load_by_params(params)

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Fetch pull requests updated within [start, end] and yield in batches."""
        params = self._build_params(
            start=start,
            end=end,
        )
        yield from self._load_by_params(params)

    def retrieve_all_slim_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> Iterator[list[SlimDocument]]:
        """Return only document IDs for all pull requests for pruning checks."""
        batch: list[SlimDocument] = []
        params = self._build_params(
            fields=SLIM_PR_LIST_RESPONSE_FIELDS,
            start=start,
            end=end,
        )
        for slug in self._iter_target_repositories():
            try:
                for pr in self._iter_pull_requests_for_repo(slug, params=params):
                    try:
                        pr_id = pr["id"]
                        doc_id = f"{DocumentSource.BITBUCKET.value}:{self.workspace}:{slug}:pr:{pr_id}"
                        batch.append(SlimDocument(id=doc_id))
                        if len(batch) >= self.batch_size:
                            yield batch
                            batch = []
                            if callback:
                                if callback.should_stop():
                                    raise RuntimeError(
                                        "bitbucket_pr_sync: Stop signal detected"
                                    )
                                callback.progress("bitbucket_pr_sync", 1)
                    except Exception as e:
                        logger.error(
                            f"Failed to build slim document for a PR in repo '{slug}'. Skipping PR.",
                            exc_info=e,
                        )
            except Exception as e:
                logger.error(
                    f"Failed to fetch PRs for repository '{slug}' for slim retrieval. Continuing with next repo.",
                    exc_info=e,
                )
        if batch:
            yield batch

    def validate_connector_settings(self) -> None:
        """Validate Bitbucket credentials and workspace access by probing a lightweight endpoint.

        Raises:
            CredentialExpiredError: on HTTP 401
            InsufficientPermissionsError: on HTTP 403
            UnexpectedValidationError: on any other failure
        """
        try:
            with self._client() as client:
                url = f"https://api.bitbucket.org/2.0/repositories/{self.workspace}"
                resp = client.get(url, params={"pagelen": 1, "fields": "pagelen"})
                if resp.status_code == 401:
                    raise CredentialExpiredError(
                        "Invalid or expired Bitbucket credentials (HTTP 401)."
                    )
                if resp.status_code == 403:
                    raise InsufficientPermissionsError(
                        "Insufficient permissions to access Bitbucket workspace (HTTP 403)."
                    )
                if resp.status_code < 200 or resp.status_code >= 300:
                    raise UnexpectedValidationError(
                        f"Unexpected Bitbucket error (status={resp.status_code})."
                    )
        except Exception as e:
            # Network or other unexpected errors
            if isinstance(
                e,
                (
                    CredentialExpiredError,
                    InsufficientPermissionsError,
                    UnexpectedValidationError,
                ),
            ):
                raise
            raise UnexpectedValidationError(
                f"Unexpected error while validating Bitbucket settings: {e}"
            )
