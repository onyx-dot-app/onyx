"""Unit tests for onyx.utils.github."""

from collections.abc import Iterable
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests

from onyx.utils.github import download_github_repo
from onyx.utils.github import GITHUB_TARBALL_URL
from onyx.utils.github import parse_github_repo


class TestParseGithubRepo:
    def test_https_plain(self) -> None:
        assert parse_github_repo("https://github.com/onyx-dot-app/onyx") == (
            "onyx-dot-app",
            "onyx",
        )

    def test_https_with_dot_git(self) -> None:
        assert parse_github_repo("https://github.com/onyx-dot-app/onyx.git") == (
            "onyx-dot-app",
            "onyx",
        )

    def test_https_with_trailing_path(self) -> None:
        assert parse_github_repo(
            "https://github.com/onyx-dot-app/onyx/tree/main/backend"
        ) == ("onyx-dot-app", "onyx")

    def test_https_with_query_and_fragment(self) -> None:
        assert parse_github_repo("https://github.com/onyx-dot-app/onyx?foo=bar") == (
            "onyx-dot-app",
            "onyx",
        )
        assert parse_github_repo("https://github.com/onyx-dot-app/onyx#readme") == (
            "onyx-dot-app",
            "onyx",
        )

    def test_http_scheme(self) -> None:
        assert parse_github_repo("http://github.com/onyx-dot-app/onyx") == (
            "onyx-dot-app",
            "onyx",
        )

    def test_ssh_plain(self) -> None:
        assert parse_github_repo("git@github.com:onyx-dot-app/onyx") == (
            "onyx-dot-app",
            "onyx",
        )

    def test_ssh_with_dot_git(self) -> None:
        assert parse_github_repo("git@github.com:onyx-dot-app/onyx.git") == (
            "onyx-dot-app",
            "onyx",
        )

    def test_short_form(self) -> None:
        assert parse_github_repo("onyx-dot-app/onyx") == ("onyx-dot-app", "onyx")

    def test_short_form_with_dot_git(self) -> None:
        assert parse_github_repo("onyx-dot-app/onyx.git") == (
            "onyx-dot-app",
            "onyx",
        )

    def test_strips_whitespace(self) -> None:
        assert parse_github_repo("  onyx-dot-app/onyx  ") == (
            "onyx-dot-app",
            "onyx",
        )

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "   ",
            "not a repo",
            "https://gitlab.com/owner/repo",
            "https://github.com/onlyowner",
            "owner/",
            "/repo",
        ],
    )
    def test_invalid_raises(self, bad: str) -> None:
        with pytest.raises(ValueError):
            parse_github_repo(bad)


def _mock_response(chunks: Iterable[bytes], status_code: int = 200) -> MagicMock:
    """Build a MagicMock that quacks like a streamed ``requests.Response``."""
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.iter_content.return_value = iter(list(chunks))
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"HTTP {status_code}"
        )
    else:
        response.raise_for_status.return_value = None
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


class TestDownloadGithubRepo:
    def test_returns_concatenated_body(self) -> None:
        response = _mock_response([b"foo", b"bar", b"baz"])
        with patch("onyx.utils.github.requests.get", return_value=response) as mock_get:
            result = download_github_repo("onyx-dot-app/onyx")

        assert result == b"foobarbaz"
        mock_get.assert_called_once()

    def test_skips_empty_keepalive_chunks(self) -> None:
        response = _mock_response([b"foo", b"", b"bar"])
        with patch("onyx.utils.github.requests.get", return_value=response):
            assert download_github_repo("onyx-dot-app/onyx") == b"foobar"

    def test_builds_tarball_url_from_owner_and_name(self) -> None:
        response = _mock_response([b""])
        with patch("onyx.utils.github.requests.get", return_value=response) as mock_get:
            download_github_repo("https://github.com/onyx-dot-app/onyx.git")

        called_url = mock_get.call_args.args[0]
        assert called_url == GITHUB_TARBALL_URL.format(
            owner="onyx-dot-app", repo="onyx"
        )

    def test_sets_authorization_header_when_token_provided(self) -> None:
        response = _mock_response([b""])
        with patch("onyx.utils.github.requests.get", return_value=response) as mock_get:
            download_github_repo("onyx-dot-app/onyx", github_token="ghp_secret")

        headers = mock_get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer ghp_secret"
        assert headers["Accept"] == "application/vnd.github+json"

    def test_omits_authorization_header_when_no_token(self) -> None:
        response = _mock_response([b""])
        with patch("onyx.utils.github.requests.get", return_value=response) as mock_get:
            download_github_repo("onyx-dot-app/onyx")

        headers = mock_get.call_args.kwargs["headers"]
        assert "Authorization" not in headers

    def test_uses_streaming_with_split_timeout(self) -> None:
        response = _mock_response([b""])
        with patch("onyx.utils.github.requests.get", return_value=response) as mock_get:
            download_github_repo("onyx-dot-app/onyx")

        kwargs = mock_get.call_args.kwargs
        assert kwargs["stream"] is True
        assert kwargs["allow_redirects"] is True
        timeout = kwargs["timeout"]
        assert isinstance(timeout, tuple)
        assert len(timeout) == 2

    def test_raises_when_exceeds_max_size(self) -> None:
        response = _mock_response([b"x" * 10, b"x" * 10])
        with patch("onyx.utils.github.requests.get", return_value=response):
            with pytest.raises(ValueError, match="exceeded max_size_bytes"):
                download_github_repo("onyx-dot-app/onyx", max_size_bytes=15)

    def test_propagates_http_errors(self) -> None:
        response = _mock_response([], status_code=404)
        with patch("onyx.utils.github.requests.get", return_value=response):
            with pytest.raises(requests.HTTPError):
                download_github_repo("onyx-dot-app/onyx")

    def test_invalid_repo_raises_before_request(self) -> None:
        with patch("onyx.utils.github.requests.get") as mock_get:
            with pytest.raises(ValueError):
                download_github_repo("not a repo")
        mock_get.assert_not_called()
