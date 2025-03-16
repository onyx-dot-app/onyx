import time
from collections.abc import Iterator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import cast

from github import Github
from github import RateLimitExceededException
from github import Repository
from github.GithubException import GithubException
from github.Issue import Issue
from github.PaginatedList import PaginatedList
from github.PullRequest import PullRequest

from onyx.configs.app_configs import GITHUB_CONNECTOR_BASE_URL
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger

logger = setup_logger()


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
) -> list[Any]:
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


def _batch_github_objects(
    git_objs: PaginatedList, github_client: Github, batch_size: int
) -> Iterator[list[Any]]:
    page_num = 0
    while True:
        batch = _get_batch_rate_limited(git_objs, page_num, github_client)
        page_num += 1

        if not batch:
            break

        for mini_batch in batch_generator(batch, batch_size=batch_size):
            yield mini_batch


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
        doc_updated_at=pull_request.updated_at.replace(tzinfo=timezone.utc),
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


class GithubConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        repo_owner: str,
        repositories: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        state_filter: str = "all",
        include_prs: bool = True,
        include_issues: bool = False,
    ) -> None:
        self.repo_owner = repo_owner
        self.repositories = repositories
        self.batch_size = batch_size
        self.state_filter = state_filter
        self.include_prs = include_prs
        self.include_issues = include_issues
        self.github_client: Github | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.github_client = (
            Github(
                credentials["github_access_token"], base_url=GITHUB_CONNECTOR_BASE_URL
            )
            if GITHUB_CONNECTOR_BASE_URL
            else Github(credentials["github_access_token"])
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
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        if self.github_client is None:
            raise ConnectorMissingCredentialError("GitHub")

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

        for repo in repos:
            if self.include_prs:
                logger.info(f"Fetching PRs for repo: {repo.name}")
                pull_requests = repo.get_pulls(
                    state=self.state_filter, sort="updated", direction="desc"
                )

                for pr_batch in _batch_github_objects(
                    pull_requests, self.github_client, self.batch_size
                ):
                    doc_batch: list[Document] = []
                    for pr in pr_batch:
                        if start is not None and pr.updated_at < start:
                            yield doc_batch
                            break
                        if end is not None and pr.updated_at > end:
                            continue
                        doc_batch.append(_convert_pr_to_document(cast(PullRequest, pr)))
                    yield doc_batch

            if self.include_issues:
                logger.info(f"Fetching issues for repo: {repo.name}")
                issues = repo.get_issues(
                    state=self.state_filter, sort="updated", direction="desc"
                )

                for issue_batch in _batch_github_objects(
                    issues, self.github_client, self.batch_size
                ):
                    doc_batch = []
                    for issue in issue_batch:
                        issue = cast(Issue, issue)
                        if start is not None and issue.updated_at < start:
                            yield doc_batch
                            break
                        if end is not None and issue.updated_at > end:
                            continue
                        if issue.pull_request is not None:
                            # PRs are handled separately
                            continue
                        doc_batch.append(_convert_issue_to_document(issue))
                    yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._fetch_from_github()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.utcfromtimestamp(start)
        end_datetime = datetime.utcfromtimestamp(end)

        # Move start time back by 3 hours, since some Issues/PRs are getting dropped
        # Could be due to delayed processing on GitHub side
        # The non-updated issues since last poll will be shortcut-ed and not embedded
        adjusted_start_datetime = start_datetime - timedelta(hours=3)

        epoch = datetime.utcfromtimestamp(0)
        if adjusted_start_datetime < epoch:
            adjusted_start_datetime = epoch

        return self._fetch_from_github(adjusted_start_datetime, end_datetime)

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


if __name__ == "__main__":
    import os

    connector = GithubConnector(
        repo_owner=os.environ["REPO_OWNER"],
        repositories=os.environ["REPOSITORIES"],
    )
    connector.load_credentials(
        {"github_access_token": os.environ["GITHUB_ACCESS_TOKEN"]}
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))
