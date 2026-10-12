import base64
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from github import GithubException, RateLimitExceededException
from github.GithubException import BadCredentialsException, UnknownObjectException

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.github import source_operations as github_ops
from onyx.connectors.github.models import (
    GitHubRepository,
    GitHubTokenKind,
)
from onyx.connectors.github.source_operations import (
    GitHubApiError,
    GitHubRateLimitError,
    GitHubSourceOperations,
)
from onyx.server.security.models import SSRFProtectionLevel
from tests.unit.onyx.connectors.github.conftest import raw_repository

_CLASSIC_TOKEN = "ghp_classic"
_FINE_GRAINED_TOKEN = "github_pat_fine"


def _gateway(
    token: str = _CLASSIC_TOKEN, **credentials: Any
) -> tuple[GitHubSourceOperations, MagicMock]:
    """A gateway whose client's requester is a mock: set its
    ``requestJsonAndCheck`` to script the responses."""
    gateway = GitHubSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None, "github", {"github_access_token": token, **credentials}
        )
    )
    client = MagicMock()
    gateway._cached_client = client
    return gateway, client.requester.requestJsonAndCheck


def _raw_pr(number: int) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"PR {number}",
        "state": "open",
        "html_url": f"https://github.com/o/r/pull/{number}",
        "updated_at": "2024-05-01T12:00:00Z",
        "created_at": "2024-05-01T11:00:00Z",
        "user": {"login": "octocat"},
        "assignees": [{"login": "hubot"}],
        "labels": [{"name": "bug"}],
        "base": {"repo": {"full_name": "o/r"}},
    }


def _link(next_url: str) -> dict[str, str]:
    return {"link": f'<{next_url}>; rel="next", <{next_url}9>; rel="last"'}


# --- error translation ---


@pytest.mark.parametrize(
    "error",
    [
        BadCredentialsException(401, {"message": "Bad credentials"}, {}),
        UnknownObjectException(404, {"message": "Not Found"}, {}),
        GithubException(500, {"message": "Server Error"}, {}),
    ],
    ids=["401", "404", "500"],
)
def test_sdk_errors_leave_as_api_errors(error: GithubException) -> None:
    gateway, request = _gateway()
    request.side_effect = error

    with pytest.raises(GitHubApiError) as excinfo:
        gateway.get_repository(owner="o", name="r")

    assert not isinstance(excinfo.value, GitHubRateLimitError)
    assert excinfo.value.status_code == error.status
    assert excinfo.value.github_message == error.data["message"]
    assert excinfo.value.__cause__ is error


def test_primary_rate_limit_is_a_rate_limit_error() -> None:
    gateway, request = _gateway()
    request.side_effect = RateLimitExceededException(
        403, {"message": "API rate limit exceeded for user ID 1."}, {}
    )

    with pytest.raises(GitHubRateLimitError) as excinfo:
        gateway.get_repository(owner="o", name="r")

    assert excinfo.value.secondary is False


def test_secondary_rate_limit_is_a_rate_limit_error() -> None:
    gateway, request = _gateway()
    request.side_effect = RateLimitExceededException(
        403,
        {"message": "You have exceeded a secondary rate limit. Please wait."},
        {"retry-after": "60"},
    )

    with pytest.raises(GitHubRateLimitError) as excinfo:
        gateway.get_repository(owner="o", name="r")

    assert excinfo.value.secondary is True


@pytest.mark.parametrize(
    "status,headers",
    [(429, {}), (403, {"x-ratelimit-remaining": "0"})],
    ids=["429", "403-no-remaining"],
)
def test_other_rate_limit_responses_are_rate_limit_errors(
    status: int, headers: dict[str, str]
) -> None:
    gateway, request = _gateway()
    request.side_effect = GithubException(status, {"message": "slow down"}, headers)

    with pytest.raises(GitHubRateLimitError):
        gateway.get_repository(owner="o", name="r")


def test_a_denial_names_what_the_endpoint_accepts() -> None:
    gateway, request = _gateway(_FINE_GRAINED_TOKEN)
    request.side_effect = GithubException(
        403,
        {"message": "Resource not accessible by personal access token"},
        {
            "x-accepted-github-permissions": "pull_requests=read",
            "x-ratelimit-remaining": "4999",
        },
    )

    with pytest.raises(GitHubApiError) as excinfo:
        gateway.list_pull_requests(repo_full_name="o/r", state="all", page=0)

    assert not isinstance(excinfo.value, GitHubRateLimitError)
    assert excinfo.value.status_code == 403
    assert excinfo.value.accepted_permissions == "pull_requests=read"


def test_a_saml_denial_is_marked() -> None:
    gateway, request = _gateway()
    request.side_effect = GithubException(
        403,
        {"message": "Resource protected by organization SAML enforcement."},
        {"x-github-sso": "required; url=https://github.com/orgs/acme/sso"},
    )

    with pytest.raises(GitHubApiError) as excinfo:
        gateway.get_organization(login="acme")

    assert excinfo.value.sso_required


def test_an_error_raised_while_iterating_is_translated() -> None:
    """A generator operation reads pages lazily; an error on a later page
    leaves the gateway translated, after the first page's items."""
    gateway, request = _gateway()
    request.side_effect = [
        (_link("https://api.github.com/repos/o/r/pulls?page=2"), [_raw_pr(1)]),
        RateLimitExceededException(403, {"message": "API rate limit exceeded"}, {}),
    ]

    items: Iterator[Any] = gateway.iter_pull_requests_by_cursor(
        repo_full_name="o/r", state="all"
    )

    first = next(items)
    assert first.item.number == 1
    with pytest.raises(GitHubRateLimitError):
        next(items)


# --- pagination ---


def test_offset_pages_send_the_page_like_pygithub() -> None:
    gateway, request = _gateway()
    request.return_value = ({}, [_raw_pr(1)])

    gateway.list_pull_requests(repo_full_name="o/r", state="open", page=0)
    gateway.list_pull_requests(repo_full_name="o/r", state="open", page=2)

    first_params = request.call_args_list[0].kwargs["parameters"]
    second_params = request.call_args_list[1].kwargs["parameters"]
    assert first_params == {
        "state": "open",
        "sort": "updated",
        "direction": "desc",
        "per_page": 100,
    }
    assert second_params["page"] == 3


def test_listings_follow_the_link_header() -> None:
    gateway, request = _gateway()
    next_url = "https://api.github.com/orgs/acme/members?filter=all&page=2"
    request.side_effect = [
        (_link(next_url), [{"login": "a"}]),
        ({}, [{"login": "b"}]),
    ]

    assert gateway.list_organization_members(org_login="acme") == ["a", "b"]
    first, second = request.call_args_list
    assert first.args == ("GET", "/orgs/acme/members")
    assert first.kwargs["parameters"] == {"filter": "all", "per_page": 100}
    # A next URL carries its own query.
    assert second.args == ("GET", next_url)
    assert second.kwargs["parameters"] is None


def test_cursor_listing_resumes_at_the_cursor_and_skips() -> None:
    gateway, request = _gateway()
    cursor = "https://api.github.com/repos/o/r/pulls?after=abc"
    request.return_value = ({}, [_raw_pr(1), _raw_pr(2), _raw_pr(3)])

    items = list(
        gateway.iter_pull_requests_by_cursor(
            repo_full_name="o/r", state="all", cursor_url=cursor, skip=2
        )
    )

    assert [item.item.number for item in items] == [3]
    assert items[0].next_url is None
    assert request.call_args.args == ("GET", cursor)


def test_repository_listing_stops_at_the_limit() -> None:
    gateway, request = _gateway()
    request.return_value = (
        _link("https://api.github.com/orgs/acme/repos?page=2"),
        [raw_repository(name="a"), raw_repository(name="b")],
    )

    repos = gateway.list_organization_repositories(org_login="acme", limit=1)

    assert [repo.name for repo in repos] == ["a"]
    assert request.call_count == 1


# --- plain data ---


def test_pull_requests_are_plain_data() -> None:
    gateway, request = _gateway()
    request.return_value = ({}, [_raw_pr(7)])

    (pull_request,) = gateway.list_pull_requests(
        repo_full_name="o/r", state="all", page=0
    )

    assert pull_request.number == 7
    assert pull_request.user_login == "octocat"
    assert pull_request.assignee_logins == ["hubot"]
    assert pull_request.label_names == ["bug"]
    assert pull_request.base_repo_full_name == "o/r"
    assert pull_request.updated_at == datetime(2024, 5, 1, 12, tzinfo=timezone.utc)
    assert not pull_request.detailed


def test_a_listed_repository_takes_its_organization_from_the_owner() -> None:
    repo = GitHubRepository.from_raw(raw_repository())
    user_repo = GitHubRepository.from_raw(
        raw_repository(owner="octocat")
        | {"owner": {"login": "octocat", "id": 7, "type": "User"}}
    )

    assert repo.organization is not None
    assert (repo.organization.id, repo.organization.login) == (100, "test-org")
    assert user_repo.organization is None


def test_file_content_is_decoded() -> None:
    gateway, request = _gateway()
    request.return_value = (
        {},
        {"encoding": "base64", "content": base64.b64encode(b"# Hi").decode()},
    )

    content = gateway.get_file_content(
        repo_full_name="o/r", path="README.md", ref="main"
    )

    assert content.content == b"# Hi"
    request.assert_called_once_with(
        "GET", "/repos/o/r/contents/README.md", parameters={"ref": "main"}
    )


def test_file_content_without_base64_has_no_bytes() -> None:
    gateway, request = _gateway()
    request.return_value = ({}, {"encoding": "none", "content": ""})

    content = gateway.get_file_content(repo_full_name="o/r", path="big.md", ref="main")

    assert content.content is None
    assert content.encoding == "none"


def test_a_directory_is_not_a_file() -> None:
    gateway, request = _gateway()
    request.return_value = ({}, [{"name": "a.md"}])

    with pytest.raises(ValueError, match="got a directory"):
        gateway.get_file_content(repo_full_name="o/r", path="docs", ref="main")


@pytest.mark.parametrize(
    "token,scopes_header,kind,scopes",
    [
        (
            _CLASSIC_TOKEN,
            "repo, read:org",
            GitHubTokenKind.CLASSIC,
            ["repo", "read:org"],
        ),
        (_CLASSIC_TOKEN, "", GitHubTokenKind.CLASSIC, []),
        (_FINE_GRAINED_TOKEN, None, GitHubTokenKind.FINE_GRAINED, None),
        ("0123abcd", None, GitHubTokenKind.OTHER, None),
    ],
)
def test_token_info_reads_the_scopes_header(
    token: str,
    scopes_header: str | None,
    kind: GitHubTokenKind,
    scopes: list[str] | None,
) -> None:
    gateway, request = _gateway(token)
    headers = {} if scopes_header is None else {"x-oauth-scopes": scopes_header}
    request.return_value = (headers, {"login": "octocat"})

    info = gateway.get_token_info()

    assert (info.login, info.kind, info.scopes) == ("octocat", kind, scopes)


def test_rate_limit_reset_is_a_utc_time() -> None:
    gateway, request = _gateway()
    request.return_value = ({}, {"resources": {"core": {"reset": 1700000000}}})

    assert gateway.get_rate_limit_reset() == datetime.fromtimestamp(
        1700000000, tz=timezone.utc
    )


# --- client ---


def test_the_client_is_built_once_with_the_bounded_retry() -> None:
    gateway = GitHubSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None, "github", {"github_access_token": _CLASSIC_TOKEN}
        )
    )
    with (
        patch.object(github_ops, "Github") as github_cls,
        patch("onyx.connectors.github.utils.GITHUB_CONNECTOR_BASE_URL", None),
    ):
        gateway._client()
        gateway._client()

    github_cls.assert_called_once()
    assert isinstance(
        github_cls.call_args.kwargs["retry"], github_ops.BoundedGithubRetry
    )
    assert "base_url" not in github_cls.call_args.kwargs


def test_an_unsafe_credential_url_fails_on_the_first_call() -> None:
    """The checks runner builds the gateway without the connector, so the
    gateway checks the Enterprise Server URL itself."""
    gateway = GitHubSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None,
            "github",
            {
                "github_access_token": _CLASSIC_TOKEN,
                "github_base_url": "https://169.254.169.254",
            },
        )
    )
    with patch("onyx.connectors.github.utils.get_security_settings") as settings:
        settings.return_value.ssrf_protection_level = SSRFProtectionLevel.VALIDATE_ALL
        with pytest.raises(ConnectorValidationError):
            gateway.get_token_info()
