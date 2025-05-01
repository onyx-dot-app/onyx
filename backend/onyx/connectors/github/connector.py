import copy
import time
from collections.abc import Callable
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
CURSOR_LOG_FREQUENCY = 100

_MAX_NUM_RATE_LIMIT_RETRIES = 5


def _sleep_after_rate_limit_exception(github_client: Github) -> None:
    sleep_time = github_client.get_rate_limit().core.reset.replace(
        tzinfo=timezone.utc
    ) - datetime.now(tz=timezone.utc)
    sleep_time += timedelta(minutes=1)  # add an extra minute just to be safe
    logger.notice(f"Ran into Github rate-limit. Sleeping {sleep_time.seconds} seconds.")
    time.sleep(sleep_time.seconds)


# Cases
# X (from start) standard run, no fallback to cursor-based pagination
# X (from start) standard run errors, fallback to cursor-based pagination
#  X error in the middle of a page
#  X no errors: run to completion
# X (from checkpoint) standard run, no fallback to cursor-based pagination
# X (from checkpoint) continue from cursor-based pagination
#  - retrying
#  - no retrying

# things to check:
# checkpoint state on return
# checkpoint progress (no infinite loop)


def _paginate_until_error(
    git_objs: Callable[[], PaginatedList[PullRequest | Issue]],
    cursor_url: str | None,
    prev_num_objs: int,
    cursor_url_callback: Callable[[str | None, int], None],
    retrying: bool = False,
) -> Generator[PullRequest | Issue, None, None]:
    num_objs = prev_num_objs
    pag_list = git_objs()
    if cursor_url:
        pag_list.__nextUrl = cursor_url
    elif retrying:
        # if we are retrying, we want to skip the objects retrieved
        # over previous calls. Unfortunately, this WILL retrieve all
        # pages before the one we are resuming from, so we really
        # don't want this case to be hit often
        logger.warning(
            "Retrying from a previous cursor-based pagination call. "
            "This will retrieve all pages before the one we are resuming from, "
            "which may take a while and consume many API calls."
        )
        pag_list = pag_list[prev_num_objs:]
        num_objs = 0

    try:
        # this for loop handles cursor-based pagination
        for issue_or_pr in pag_list:
            num_objs += 1
            yield issue_or_pr
            # used to store the current cursor url in the checkpoint. This value
            # is updated during iteration over pag_list.
            cursor_url_callback(pag_list.__nextUrl, num_objs)

            if num_objs % CURSOR_LOG_FREQUENCY == 0:
                logger.info(
                    f"Retrieved {num_objs} objects with current cursor url: {pag_list.__nextUrl}"
                )

    except Exception as e:
        logger.exception(f"Error during cursor-based pagination: {e}")
        if num_objs - prev_num_objs > 0:
            raise

        if pag_list.__nextUrl is not None and not retrying:
            logger.info(
                "Assuming that this error is due to cursor "
                "expiration because no objects were retrieved. "
                "Retrying from the first page."
            )
            yield from _paginate_until_error(
                git_objs, None, prev_num_objs, cursor_url_callback, retrying=True
            )
            return

        # for no cursor url or if we reach this point after a retry, raise the error
        raise


def _get_batch_rate_limited(
    # We pass in a callable because we want git_objs to produce a fresh
    # PaginatedList each time it's called to avoid using the same object for cursor-based pagination
    # from a partial offset-based pagination call.
    git_objs: Callable[[], PaginatedList],
    page_num: int,
    cursor_url: str | None,
    prev_num_objs: int,
    cursor_url_callback: Callable[[str | None, int], None],
    github_client: Github,
    attempt_num: int = 0,
) -> Generator[PullRequest | Issue, None, None]:
    if attempt_num > _MAX_NUM_RATE_LIMIT_RETRIES:
        raise RuntimeError(
            "Re-tried fetching batch too many times. Something is going wrong with fetching objects from Github"
        )
    try:
        if cursor_url:
            # when this is set, we are resuming from an earlier
            # cursor-based pagination call.
            yield from _paginate_until_error(
                git_objs, cursor_url, prev_num_objs, cursor_url_callback
            )
            return
        objs = list(git_objs().get_page(page_num))
        # fetch all data here to disable lazy loading later
        # this is needed to capture the rate limit exception here (if one occurs)
        for obj in objs:
            if hasattr(obj, "raw_data"):
                getattr(obj, "raw_data")
        yield from objs
    except RateLimitExceededException:
        _sleep_after_rate_limit_exception(github_client)
        yield from _get_batch_rate_limited(
            git_objs,
            page_num,
            cursor_url,
            prev_num_objs,
            cursor_url_callback,
            github_client,
            attempt_num + 1,
        )
    except GithubException as e:
        if not (
            e.status == 422
            and (
                "cursor" in (e.message or "")
                or "cursor" in (e.data or {}).get("message", "")
            )
        ):
            raise
        # Fallback to a cursor-based pagination strategy
        # This can happen for "large datasets," but there's no documentation
        # On the error on the web as far as we can tell.
        # Error message:
        # "Pagination with the page parameter is not supported for large datasets,
        # please use cursor based pagination (after/before)"
        yield from _paginate_until_error(
            git_objs, cursor_url, prev_num_objs, cursor_url_callback
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

    # Used for the fallback cursor-based pagination strategy
    num_retrieved: int
    cursor_url: str | None = None

    def reset(self) -> None:
        """
        Resets curr_page, num_retrieved, and cursor_url to their initial values (0, 0, None)
        """
        self.curr_page = 0
        self.num_retrieved = 0
        self.cursor_url = None


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

            curr_repo = repos.pop()
            checkpoint.cached_repo_ids = [repo.id for repo in repos]
            checkpoint.cached_repo = SerializedRepository(
                id=curr_repo.id,
                headers=curr_repo.raw_headers,
                raw_data=curr_repo.raw_data,
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

        def cursor_url_callback(cursor_url: str | None, num_objs: int) -> None:
            checkpoint.cursor_url = cursor_url
            checkpoint.num_retrieved = num_objs

        # TODO: all PRs are also issues, so we should be able to _only_ get issues
        # and then filter appropriately whenever include_issues is True
        if self.include_prs and checkpoint.stage == GithubConnectorStage.PRS:
            logger.info(f"Fetching PRs for repo: {repo.name}")

            def pull_requests_func() -> PaginatedList[PullRequest]:
                return repo.get_pulls(
                    state=self.state_filter, sort="updated", direction="desc"
                )

            pr_batch = _get_batch_rate_limited(
                pull_requests_func,
                checkpoint.curr_page,
                checkpoint.cursor_url,
                checkpoint.num_retrieved,
                cursor_url_callback,
                self.github_client,
            )
            checkpoint.curr_page += 1  # NOTE: not used for cursor-based fallback
            done_with_prs = False
            num_prs = 0
            pr = None
            for pr in pr_batch:
                num_prs += 1

                # we iterate backwards in time, so at this point we stop processing prs
                if (
                    start is not None
                    and pr.updated_at
                    and pr.updated_at.replace(tzinfo=timezone.utc) < start
                ):
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
                    yield _convert_pr_to_document(cast(PullRequest, pr))
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

            # If we reach this point with a cursor url in the checkpoint, we were using
            # the fallback cursor-based pagination strategy. That strategy tries to get all
            # PRs, so having curosr_url set means we are done with prs. However, we need to
            # return AFTER the checkpoint reset to avoid infinite loops.

            # if we found any PRs on the page and there are more PRs to get, return the checkpoint.
            # In offset mode, while indexing without time constraints, the pr batch
            # will be empty when we're done.
            if num_prs > 0 and not done_with_prs and not checkpoint.cursor_url:
                return checkpoint

            # if we went past the start date during the loop or there are no more
            # prs to get, we move on to issues
            checkpoint.stage = GithubConnectorStage.ISSUES
            checkpoint.reset()

            if checkpoint.cursor_url:
                # save the checkpoint after changing stage; next run will continue from issues
                return checkpoint

        checkpoint.stage = GithubConnectorStage.ISSUES

        if self.include_issues and checkpoint.stage == GithubConnectorStage.ISSUES:
            logger.info(f"Fetching issues for repo: {repo.name}")

            def issues_func() -> PaginatedList[Issue]:
                return repo.get_issues(
                    state=self.state_filter, sort="updated", direction="desc"
                )

            issue_batch = list(
                _get_batch_rate_limited(
                    issues_func,
                    checkpoint.curr_page,
                    checkpoint.cursor_url,
                    checkpoint.num_retrieved,
                    cursor_url_callback,
                    self.github_client,
                )
            )
            checkpoint.curr_page += 1
            done_with_issues = False
            num_issues = 0
            for issue in issue_batch:
                num_issues += 1
                issue = cast(Issue, issue)
                # we iterate backwards in time, so at this point we stop processing prs
                if (
                    start is not None
                    and issue.updated_at.replace(tzinfo=timezone.utc) < start
                ):
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
                    # TODO: but they shouldn't always be
                    continue

                try:
                    yield _convert_issue_to_document(issue)
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

            # if we found any issues on the page, and we're not done, return the checkpoint.
            # don't return if we're using cursor-based pagination to avoid infinite loops
            if num_issues > 0 and not done_with_issues and not checkpoint.cursor_url:
                return checkpoint

            # if we went past the start date during the loop or there are no more
            # issues to get, we move on to the next repo
            checkpoint.stage = GithubConnectorStage.PRS
            checkpoint.reset()

        checkpoint.has_more = len(checkpoint.cached_repo_ids) > 0
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
            stage=GithubConnectorStage.PRS, curr_page=0, has_more=True, num_retrieved=0
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
