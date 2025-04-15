import copy
import time
from collections.abc import Generator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from enum import Enum
from typing import Any
from typing import cast

from github import Github
from github import RateLimitExceededException
from github import Repository
from github.GithubException import GithubException
from github.Issue import Issue
from github.PaginatedList import PaginatedList
from github.PullRequest import PullRequest
from github.Requester import Requester
from pydantic import BaseModel
from typing_extensions import override

from onyx.configs.app_configs import GITHUB_CONNECTOR_BASE_URL
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import ConnectorCheckpoint
from onyx.connectors.interfaces import ConnectorFailure
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

ITEMS_PER_PAGE = 100

_MAX_NUM_RATE_LIMIT_RETRIES = 5


def _sleep_after_rate_limit_exception(github_client: Github) -> None:
    sleep_time = github_client.get_rate_limit().core.reset.replace(
        tzinfo=timezone.utc
    ) - datetime.now(tz=timezone.utc)
    sleep_time += timedelta(minutes=1)  # add an extra minute just to be safe
    logger.notice(f"Ran into Github rate-limit. Sleeping {sleep_time.seconds} seconds.")
    time.sleep(sleep_time.seconds)


def _get_batch_rate_limited(
    git_objs: PaginatedList, page_num: int, github_client: Github, attempt_num: int = 0
) -> list[PullRequest | Issue]:
    if attempt_num > _MAX_NUM_RATE_LIMIT_RETRIES:
        raise RuntimeError(
            "Re-tried fetching batch too many times. Something is going wrong with fetching objects from Github"
        )

    try:
        objs = list(git_objs.get_page(page_num))
        # fetch all data here to disable lazy loading later
        # this is needed to capture the rate limit exception here (if one occurs)
        for obj in objs:
            if hasattr(obj, "raw_data"):
                getattr(obj, "raw_data")
        return objs
    except RateLimitExceededException:
        _sleep_after_rate_limit_exception(github_client)
        return _get_batch_rate_limited(
            git_objs, page_num, github_client, attempt_num + 1
        )


def _convert_pr_to_document(pull_request: PullRequest) -> Document:
    return Document(
        id=pull_request.html_url,
        sections=[
            TextSection(link=pull_request.html_url, text=pull_request.body or "")
        ],
        source=DocumentSource.GITHUB,
        semantic_identifier=pull_request.title,
        # updated_at is UTC time but is timezone unaware, explicitly add UTC
        # as there is logic in indexing to prevent wrong timestamped docs
        # due to local time discrepancies with UTC
        doc_updated_at=(
            pull_request.updated_at.replace(tzinfo=timezone.utc)
            if pull_request.updated_at
            else None
        ),
        metadata={
            "merged": str(pull_request.merged),
            "state": pull_request.state,
        },
    )


def _fetch_issue_comments(issue: Issue) -> str:
    comments = issue.get_comments()
    return "\nComment: ".join(comment.body for comment in comments)


def _convert_issue_to_document(issue: Issue) -> Document:
    return Document(
        id=issue.html_url,
        sections=[TextSection(link=issue.html_url, text=issue.body or "")],
        source=DocumentSource.GITHUB,
        semantic_identifier=issue.title,
        # updated_at is UTC time but is timezone unaware
        doc_updated_at=issue.updated_at.replace(tzinfo=timezone.utc),
        metadata={
            "state": issue.state,
        },
    )


class SerializedRepository(BaseModel):
    # id is part of the raw_data as well, just pulled out for convenience
    id: int
    headers: dict[str, str | int]
    raw_data: dict[str, Any]

    def to_Repository(self, requester: Requester) -> Repository.Repository:
        return Repository.Repository(
            requester, self.headers, self.raw_data, completed=True
        )


class GithubConnectorStage(Enum):
    START = "start"
    PRS = "prs"
    ISSUES = "issues"


class GithubConnectorCheckpoint(ConnectorCheckpoint):
    stage: GithubConnectorStage
    curr_page: int

    cached_repo_ids: list[int] | None = None
    cached_repo: SerializedRepository | None = None


class GithubConnector(CheckpointedConnector[GithubConnectorCheckpoint]):
    def __init__(
        self,
        repo_owner: str,
        repositories: str | None = None,
        state_filter: str = "all",
        include_prs: bool = True,
        include_issues: bool = False,
    ) -> None:
        self.repo_owner = repo_owner
        self.repositories = repositories
        self.state_filter = state_filter
        self.include_prs = include_prs
        self.include_issues = include_issues
        self.github_client: Github | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        # defaults to 30 items per page, can be set to as high as 100
        self.github_client = (
            Github(
                credentials["github_access_token"],
                base_url=GITHUB_CONNECTOR_BASE_URL,
                per_page=ITEMS_PER_PAGE,
            )
            if GITHUB_CONNECTOR_BASE_URL
            else Github(credentials["github_access_token"], per_page=ITEMS_PER_PAGE)
        )
        return None

    def _get_github_repo(
        self, github_client: Github, attempt_num: int = 0
    ) -> Repository.Repository:
        if attempt_num > _MAX_NUM_RATE_LIMIT_RETRIES:
            raise RuntimeError(
                "Re-tried fetching repo too many times. Something is going wrong with fetching objects from Github"
            )

        try:
            return github_client.get_repo(f"{self.repo_owner}/{self.repositories}")
        except RateLimitExceededException:
            _sleep_after_rate_limit_exception(github_client)
            return self._get_github_repo(github_client, attempt_num + 1)

    def _get_github_repos(
        self, github_client: Github, attempt_num: int = 0
    ) -> list[Repository.Repository]:
        """Get specific repositories based on comma-separated repo_name string."""
        if attempt_num > _MAX_NUM_RATE_LIMIT_RETRIES:
            raise RuntimeError(
                "Re-tried fetching repos too many times. Something is going wrong with fetching objects from Github"
            )

        try:
            repos = []
            # Split repo_name by comma and strip whitespace
            repo_names = [
                name.strip() for name in (cast(str, self.repositories)).split(",")
            ]

            for repo_name in repo_names:
                if repo_name:  # Skip empty strings
                    try:
                        repo = github_client.get_repo(f"{self.repo_owner}/{repo_name}")
                        repos.append(repo)
                    except GithubException as e:
                        logger.warning(
                            f"Could not fetch repo {self.repo_owner}/{repo_name}: {e}"
                        )

            return repos
        except RateLimitExceededException:
            _sleep_after_rate_limit_exception(github_client)
            return self._get_github_repos(github_client, attempt_num + 1)

    def _get_all_repos(
        self, github_client: Github, attempt_num: int = 0
    ) -> list[Repository.Repository]:
        if attempt_num > _MAX_NUM_RATE_LIMIT_RETRIES:
            raise RuntimeError(
                "Re-tried fetching repos too many times. Something is going wrong with fetching objects from Github"
            )

        try:
            # Try to get organization first
            try:
                org = github_client.get_organization(self.repo_owner)
                return list(org.get_repos())
            except GithubException:
                # If not an org, try as a user
                user = github_client.get_user(self.repo_owner)
                return list(user.get_repos())
        except RateLimitExceededException:
            _sleep_after_rate_limit_exception(github_client)
            return self._get_all_repos(github_client, attempt_num + 1)

    def _fetch_from_github(
        self,
        checkpoint: GithubConnectorCheckpoint,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Generator[Document | ConnectorFailure, None, GithubConnectorCheckpoint]:
        if self.github_client is None:
            raise ConnectorMissingCredentialError("GitHub")

        checkpoint = copy.deepcopy(checkpoint)

        # First run of the connector, fetch all repos and store in checkpoint
        if checkpoint.cached_repo_ids is None:
            repos = []
            if self.repositories:
                if "," in self.repositories:
                    # Multiple repositories specified
                    repos = self._get_github_repos(self.github_client)
                else:
                    # Single repository (backward compatibility)
                    repos = [self._get_github_repo(self.github_client)]
            else:
                # All repositories
                repos = self._get_all_repos(self.github_client)
            if not repos:
                checkpoint.has_more = False
                return checkpoint

            checkpoint.cached_repo_ids = sorted([repo.id for repo in repos])
            checkpoint.cached_repo = SerializedRepository(
                id=checkpoint.cached_repo_ids[0],
                headers=repos[0].raw_headers,
                raw_data=repos[0].raw_data,
            )
            checkpoint.stage = GithubConnectorStage.PRS
            checkpoint.curr_page = 0
            # save checkpoint with repo ids retrieved
            return checkpoint

        assert checkpoint.cached_repo is not None, "No repo saved in checkpoint"

        # Try to access the requester - different PyGithub versions may use different attribute names
        try:
            # Try direct access to a known attribute name first
            if hasattr(self.github_client, "_requester"):
                requester = self.github_client._requester
            elif hasattr(self.github_client, "_Github__requester"):
                requester = self.github_client._Github__requester
            else:
                # If we can't find the requester attribute, we need to fall back to recreating the repo
                raise AttributeError("Could not find requester attribute")

            repo = checkpoint.cached_repo.to_Repository(requester)
        except Exception as e:
            # If all else fails, re-fetch the repo directly
            logger.warning(
                f"Failed to deserialize repository: {e}. Attempting to re-fetch."
            )
            repo_id = checkpoint.cached_repo.id
            repo = self.github_client.get_repo(repo_id)

        if self.include_prs and checkpoint.stage == GithubConnectorStage.PRS:
            logger.info(f"Fetching PRs for repo: {repo.name}")
            pull_requests = repo.get_pulls(
                state=self.state_filter, sort="updated", direction="desc"
            )

            doc_batch: list[Document] = []
            pr_batch = _get_batch_rate_limited(
                pull_requests, checkpoint.curr_page, self.github_client
            )
            checkpoint.curr_page += 1
            done_with_prs = False
            for pr in pr_batch:
                # we iterate backwards in time, so at this point we stop processing prs
                if (
                    start is not None
                    and pr.updated_at
                    and pr.updated_at.replace(tzinfo=timezone.utc) < start
                ):
                    yield from doc_batch
                    done_with_prs = True
                    break
                # Skip PRs updated after the end date
                if (
                    end is not None
                    and pr.updated_at
                    and pr.updated_at.replace(tzinfo=timezone.utc) > end
                ):
                    continue
                try:
                    doc_batch.append(_convert_pr_to_document(cast(PullRequest, pr)))
                except Exception as e:
                    error_msg = f"Error converting PR to document: {e}"
                    logger.exception(error_msg)
                    yield ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=str(pr.id), document_link=pr.html_url
                        ),
                        failure_message=error_msg,
                        exception=e,
                    )
                    continue

            # if we found any PRs on the page, yield any associated documents and return the checkpoint
            if not done_with_prs and len(pr_batch) > 0:
                yield from doc_batch
                return checkpoint

            # if we went past the start date during the loop or there are no more
            # prs to get, we move on to issues
            checkpoint.stage = GithubConnectorStage.ISSUES
            checkpoint.curr_page = 0

        checkpoint.stage = GithubConnectorStage.ISSUES

        if self.include_issues and checkpoint.stage == GithubConnectorStage.ISSUES:
            logger.info(f"Fetching issues for repo: {repo.name}")
            issues = repo.get_issues(
                state=self.state_filter, sort="updated", direction="desc"
            )

            doc_batch = []
            issue_batch = _get_batch_rate_limited(
                issues, checkpoint.curr_page, self.github_client
            )
            checkpoint.curr_page += 1
            done_with_issues = False
            for issue in cast(list[Issue], issue_batch):
                # we iterate backwards in time, so at this point we stop processing prs
                if (
                    start is not None
                    and issue.updated_at.replace(tzinfo=timezone.utc) < start
                ):
                    yield from doc_batch
                    done_with_issues = True
                    break
                # Skip PRs updated after the end date
                if (
                    end is not None
                    and issue.updated_at.replace(tzinfo=timezone.utc) > end
                ):
                    continue

                if issue.pull_request is not None:
                    # PRs are handled separately
                    continue

                try:
                    doc_batch.append(_convert_issue_to_document(issue))
                except Exception as e:
                    error_msg = f"Error converting issue to document: {e}"
                    logger.exception(error_msg)
                    yield ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=str(issue.id),
                            document_link=issue.html_url,
                        ),
                        failure_message=error_msg,
                        exception=e,
                    )
                    continue

            # if we found any issues on the page, yield them and return the checkpoint
            if not done_with_issues and len(issue_batch) > 0:
                yield from doc_batch
                return checkpoint

            # if we went past the start date during the loop or there are no more
            # issues to get, we move on to the next repo
            checkpoint.stage = GithubConnectorStage.PRS
            checkpoint.curr_page = 0

        checkpoint.has_more = len(checkpoint.cached_repo_ids) > 1
        if checkpoint.cached_repo_ids:
            next_id = checkpoint.cached_repo_ids.pop()
            next_repo = self.github_client.get_repo(next_id)
            checkpoint.cached_repo = SerializedRepository(
                id=next_id,
                headers=next_repo.raw_headers,
                raw_data=next_repo.raw_data,
            )

        return checkpoint

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GithubConnectorCheckpoint,
    ) -> CheckpointOutput[GithubConnectorCheckpoint]:
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)

        # Move start time back by 3 hours, since some Issues/PRs are getting dropped
        # Could be due to delayed processing on GitHub side
        # The non-updated issues since last poll will be shortcut-ed and not embedded
        adjusted_start_datetime = start_datetime - timedelta(hours=3)

        epoch = datetime.fromtimestamp(0, tz=timezone.utc)
        if adjusted_start_datetime < epoch:
            adjusted_start_datetime = epoch

        return self._fetch_from_github(
            checkpoint, start=adjusted_start_datetime, end=end_datetime
        )

    def validate_connector_settings(self) -> None:
        if self.github_client is None:
            raise ConnectorMissingCredentialError("GitHub credentials not loaded.")

        if not self.repo_owner:
            raise ConnectorValidationError(
                "Invalid connector settings: 'repo_owner' must be provided."
            )

        try:
            if self.repositories:
                if "," in self.repositories:
                    # Multiple repositories specified
                    repo_names = [name.strip() for name in self.repositories.split(",")]
                    if not repo_names:
                        raise ConnectorValidationError(
                            "Invalid connector settings: No valid repository names provided."
                        )

                    # Validate at least one repository exists and is accessible
                    valid_repos = False
                    validation_errors = []

                    for repo_name in repo_names:
                        if not repo_name:
                            continue

                        try:
                            test_repo = self.github_client.get_repo(
                                f"{self.repo_owner}/{repo_name}"
                            )
                            test_repo.get_contents("")
                            valid_repos = True
                            # If at least one repo is valid, we can proceed
                            break
                        except GithubException as e:
                            validation_errors.append(
                                f"Repository '{repo_name}': {e.data.get('message', str(e))}"
                            )

                    if not valid_repos:
                        error_msg = (
                            "None of the specified repositories could be accessed: "
                        )
                        error_msg += ", ".join(validation_errors)
                        raise ConnectorValidationError(error_msg)
                else:
                    # Single repository (backward compatibility)
                    test_repo = self.github_client.get_repo(
                        f"{self.repo_owner}/{self.repositories}"
                    )
                    test_repo.get_contents("")
            else:
                # Try to get organization first
                try:
                    org = self.github_client.get_organization(self.repo_owner)
                    org.get_repos().totalCount  # Just check if we can access repos
                except GithubException:
                    # If not an org, try as a user
                    user = self.github_client.get_user(self.repo_owner)
                    user.get_repos().totalCount  # Just check if we can access repos

        except RateLimitExceededException:
            raise UnexpectedValidationError(
                "Validation failed due to GitHub rate-limits being exceeded. Please try again later."
            )

        except GithubException as e:
            if e.status == 401:
                raise CredentialExpiredError(
                    "GitHub credential appears to be invalid or expired (HTTP 401)."
                )
            elif e.status == 403:
                raise InsufficientPermissionsError(
                    "Your GitHub token does not have sufficient permissions for this repository (HTTP 403)."
                )
            elif e.status == 404:
                if self.repositories:
                    if "," in self.repositories:
                        raise ConnectorValidationError(
                            f"None of the specified GitHub repositories could be found for owner: {self.repo_owner}"
                        )
                    else:
                        raise ConnectorValidationError(
                            f"GitHub repository not found with name: {self.repo_owner}/{self.repositories}"
                        )
                else:
                    raise ConnectorValidationError(
                        f"GitHub user or organization not found: {self.repo_owner}"
                    )
            else:
                raise ConnectorValidationError(
                    f"Unexpected GitHub error (status={e.status}): {e.data}"
                )

        except Exception as exc:
            raise Exception(
                f"Unexpected error during GitHub settings validation: {exc}"
            )

    def validate_checkpoint_json(
        self, checkpoint_json: str
    ) -> GithubConnectorCheckpoint:
        return GithubConnectorCheckpoint.model_validate_json(checkpoint_json)

    def build_dummy_checkpoint(self) -> GithubConnectorCheckpoint:
        return GithubConnectorCheckpoint(
            stage=GithubConnectorStage.PRS, curr_page=0, has_more=True
        )


if __name__ == "__main__":
    import os

    connector = GithubConnector(
        repo_owner=os.environ["REPO_OWNER"],
        repositories=os.environ["REPOSITORIES"],
    )
    connector.load_credentials(
        {"github_access_token": os.environ["ACCESS_TOKEN_GITHUB"]}
    )
    document_batches = connector.load_from_checkpoint(
        0, time.time(), connector.build_dummy_checkpoint()
    )
    print(next(document_batches))
