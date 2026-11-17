"""``_detailed_pull_request`` when GitHub cannot detail a pull request."""

from collections.abc import Callable

import pytest

from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.models import GitHubPullRequest
from onyx.connectors.github.source_operations import GitHubApiError


def _api_error(status: int, message: str) -> GitHubApiError:
    return GitHubApiError(
        f"{status} {message}",
        status_code=status,
        github_message=message,
        method="GET",
        url="/repos/test-org/test-repo/pulls/1",
    )


def test_too_many_files_changed_keeps_the_listing_pull_request(
    build_github_connector: Callable[..., GithubConnector],
    create_pr: Callable[..., GitHubPullRequest],
    mock_source_operations,
) -> None:
    # GitHub answers GET /pulls/{n} with 422 for a diff too large to compute.
    # One such pull request must not fail the whole run.
    connector = build_github_connector()
    listed = create_pr(number=1)
    mock_source_operations.get_pull_request.side_effect = _api_error(
        422, "The request could not be processed because too many files changed"
    )

    assert connector._detailed_pull_request(listed) is listed


@pytest.mark.parametrize(
    "status,message",
    [
        (401, "Bad credentials"),
        (422, "Validation Failed"),
        (500, "Server Error"),
    ],
)
def test_other_errors_still_raise(
    build_github_connector: Callable[..., GithubConnector],
    create_pr: Callable[..., GitHubPullRequest],
    mock_source_operations,
    status: int,
    message: str,
) -> None:
    connector = build_github_connector()
    mock_source_operations.get_pull_request.side_effect = _api_error(status, message)

    with pytest.raises(GitHubApiError):
        connector._detailed_pull_request(create_pr(number=1))
