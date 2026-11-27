"""``_detailed_pull_request`` when GitHub cannot detail a pull request."""

from collections.abc import Callable

import pytest

from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.connector import _convert_pr_to_document
from onyx.connectors.github.models import GitHubPullRequest
from onyx.connectors.github.source_operations import GitHubApiError
from tests.unit.onyx.connectors.github.github_check_helpers import api_error


def test_too_many_files_changed_keeps_the_listing_pull_request(
    build_github_connector: Callable[..., GithubConnector],
    create_pr: Callable[..., GitHubPullRequest],
    mock_source_operations,
) -> None:
    # GitHub answers GET /pulls/{n} with 422 for a diff too large to compute.
    # One such pull request must not fail the whole run.
    connector = build_github_connector()
    listed = create_pr(number=1)
    mock_source_operations.get_pull_request.side_effect = api_error(
        422, "The request could not be processed because too many files changed"
    )

    assert connector._detailed_pull_request(listed) is listed


def test_an_undetailable_pull_request_is_requested_only_once(
    build_github_connector: Callable[..., GithubConnector],
    create_pr: Callable[..., GitHubPullRequest],
    mock_source_operations,
) -> None:
    # Offset paging details each PR in the batch and again at conversion; a
    # second failing request is wasted, and a rate limit on it would drop the PR.
    connector = build_github_connector()
    listed = create_pr(number=1)
    mock_source_operations.get_pull_request.side_effect = api_error(
        422, "The request could not be processed because too many files changed"
    )

    first = connector._detailed_pull_request(listed)
    second = connector._detailed_pull_request(first)

    assert second is listed
    assert mock_source_operations.get_pull_request.call_count == 1


def test_listing_pull_request_has_no_none_counts_in_metadata(
    create_pr: Callable[..., GitHubPullRequest],
) -> None:
    listed = create_pr(number=1)  # commits and changed_files are unknown

    document = _convert_pr_to_document(listed, None, lambda login: None)

    assert "num_commits" not in document.metadata
    assert "num_files_changed" not in document.metadata


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
    mock_source_operations.get_pull_request.side_effect = api_error(status, message)

    with pytest.raises(GitHubApiError):
        connector._detailed_pull_request(create_pr(number=1))
