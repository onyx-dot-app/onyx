"""Unit tests for GitHub URL parsing helper."""

import pytest

from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.connector import parse_github_url_if_needed


class TestParseGithubUrlIfNeeded:
    """Tests for defensive URL parsing in GitHub connector."""

    def test_normal_owner_no_url(self) -> None:
        """Test that regular owner names are passed through unchanged."""
        owner, repos = parse_github_url_if_needed("octocat", "repo1")
        assert owner == "octocat"
        assert repos == "repo1"

    def test_url_with_owner_only(self) -> None:
        """Test parsing URL with only owner, no repo specified."""
        owner, repos = parse_github_url_if_needed("https://github.com/octocat", None)
        assert owner == "octocat"
        assert repos is None

    def test_url_with_owner_and_repo(self) -> None:
        """Test parsing URL with both owner and repo in URL."""
        owner, repos = parse_github_url_if_needed(
            "https://github.com/octocat/repo1", None
        )
        assert owner == "octocat"
        assert repos == "repo1"

    def test_url_with_owner_but_repos_specified(self) -> None:
        """Test that explicitly specified repos take precedence over URL repo."""
        owner, repos = parse_github_url_if_needed(
            "https://github.com/octocat/repo1", "repo2,repo3"
        )
        assert owner == "octocat"
        assert repos == "repo2,repo3"

    def test_url_without_protocol(self) -> None:
        """Test parsing URL without http/https protocol."""
        owner, repos = parse_github_url_if_needed("github.com/octocat/repo1", None)
        assert owner == "octocat"
        assert repos == "repo1"

    def test_url_with_extra_path_components(self) -> None:
        """Test that extra path components (issues, PRs) are ignored."""
        owner, repos = parse_github_url_if_needed(
            "https://github.com/octocat/repo1/issues/123", None
        )
        assert owner == "octocat"
        assert repos == "repo1"

    def test_http_protocol(self) -> None:
        """Test parsing URL with http protocol."""
        owner, repos = parse_github_url_if_needed(
            "http://github.com/octocat/repo1", None
        )
        assert owner == "octocat"
        assert repos == "repo1"

    def test_github_enterprise_url(self) -> None:
        """Test that non-github.com URLs are returned as-is."""
        original = "https://github.enterprise.com/octocat/repo1"
        owner, repos = parse_github_url_if_needed(original, None)
        # Should return original since it's not github.com
        assert owner == original
        assert repos is None

    def test_empty_owner(self) -> None:
        """Test handling of empty owner string."""
        owner, repos = parse_github_url_if_needed("", None)
        assert owner == ""
        assert repos is None

    def test_url_with_trailing_slash(self) -> None:
        """Test URL with trailing slash is handled correctly."""
        owner, repos = parse_github_url_if_needed(
            "https://github.com/octocat/repo1/", None
        )
        assert owner == "octocat"
        assert repos == "repo1"

    def test_url_with_query_parameters(self) -> None:
        """Test URL with query parameters extracts owner and repo correctly."""
        owner, repos = parse_github_url_if_needed(
            "https://github.com/octocat/repo1?tab=readme", None
        )
        assert owner == "octocat"
        assert repos == "repo1"

    def test_url_with_fragment(self) -> None:
        """Test URL with fragment extracts owner and repo correctly."""
        owner, repos = parse_github_url_if_needed(
            "https://github.com/octocat/repo1#readme", None
        )
        assert owner == "octocat"
        assert repos == "repo1"

    def test_multiple_repos_preserved(self) -> None:
        """Test that multiple comma-separated repos are preserved."""
        owner, repos = parse_github_url_if_needed(
            "https://github.com/octocat", "repo1,repo2,repo3"
        )
        assert owner == "octocat"
        assert repos == "repo1,repo2,repo3"

    def test_url_only_domain_no_path(self) -> None:
        """Test URL with only domain and no path returns original."""
        original = "https://github.com"
        owner, repos = parse_github_url_if_needed(original, None)
        assert owner == original
        assert repos is None

    def test_url_with_www_subdomain(self) -> None:
        """Test URL with www subdomain is parsed correctly."""
        owner, repos = parse_github_url_if_needed(
            "https://www.github.com/octocat/repo1", None
        )
        assert owner == "octocat"
        assert repos == "repo1"

    def test_case_preservation(self) -> None:
        """Test that case is preserved in owner and repo names."""
        owner, repos = parse_github_url_if_needed(
            "https://github.com/OctoCat/MyRepo", None
        )
        assert owner == "OctoCat"
        assert repos == "MyRepo"


@pytest.mark.parametrize(
    "input_owner,input_repos,expected_owner,expected_repos",
    [
        # Normal cases
        ("facebook", "react", "facebook", "react"),
        ("microsoft", None, "microsoft", None),
        # URL cases
        ("https://github.com/facebook/react", None, "facebook", "react"),
        ("https://github.com/microsoft", "vscode", "microsoft", "vscode"),
        ("github.com/google/go", None, "google", "go"),
        # Edge cases
        (
            "https://github.com/owner/repo/tree/main",
            None,
            "owner",
            "repo",
        ),  # branch URL
        (
            "https://github.com/owner/repo/pulls",
            None,
            "owner",
            "repo",
        ),  # pulls page
    ],
)
def test_parse_github_url_parametrized(
    input_owner: str,
    input_repos: str | None,
    expected_owner: str,
    expected_repos: str | None,
) -> None:
    """Parametrized tests for various URL formats."""
    owner, repos = parse_github_url_if_needed(input_owner, input_repos)
    assert owner == expected_owner
    assert repos == expected_repos


class TestGithubConnectorUrlParsing:
    """Tests that URL parsing is applied in the GithubConnector constructor."""

    def test_connector_parses_url_in_constructor(self) -> None:
        """Test that URL parsing happens automatically in constructor."""
        connector = GithubConnector(
            repo_owner="https://github.com/octocat/hello-world",
            repositories=None,
        )
        assert connector.repo_owner == "octocat"
        assert connector.repositories == "hello-world"

    def test_connector_preserves_normal_values(self) -> None:
        """Test that normal values are preserved when not URLs."""
        connector = GithubConnector(
            repo_owner="octocat",
            repositories="repo1,repo2",
        )
        assert connector.repo_owner == "octocat"
        assert connector.repositories == "repo1,repo2"

    def test_connector_url_owner_with_explicit_repos(self) -> None:
        """Test that explicit repos take precedence over URL repo."""
        connector = GithubConnector(
            repo_owner="https://github.com/octocat/ignored-repo",
            repositories="repo1,repo2",
        )
        assert connector.repo_owner == "octocat"
        assert connector.repositories == "repo1,repo2"

    def test_connector_url_without_protocol(self) -> None:
        """Test connector handles URLs without protocol."""
        connector = GithubConnector(
            repo_owner="github.com/facebook/react",
            repositories=None,
        )
        assert connector.repo_owner == "facebook"
        assert connector.repositories == "react"
