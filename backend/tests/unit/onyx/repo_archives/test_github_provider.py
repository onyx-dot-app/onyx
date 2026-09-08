from io import BytesIO
from unittest.mock import patch

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.repo_archives.github import GitHubArchiveProvider
from onyx.utils.github import GitHubRevision, GitHubSource

MODULE = "onyx.repo_archives.github"
REPO = GitHubArchiveProvider.repo_ref("org", "repo")
SHA = "a" * 40


def test_repo_ref_identity() -> None:
    assert (REPO.provider, REPO.host, REPO.owner, REPO.name) == (
        "github",
        "github.com",
        "org",
        "repo",
    )
    assert GitHubArchiveProvider("Bearer t").authenticated
    assert not GitHubArchiveProvider().authenticated


def test_resolve_branch_and_default_branch() -> None:
    provider = GitHubArchiveProvider("Bearer t")
    with patch(
        f"{MODULE}.resolve_github_revision",
        return_value=GitHubRevision(revision=SHA, subpath=None),
    ) as resolve:
        assert provider.resolve_commit(REPO, "main") == SHA
        assert resolve.call_args.args == (
            GitHubSource(owner="org", repo="repo", tree_tail=("main",)),
            "Bearer t",
        )
        assert provider.resolve_commit(REPO, None) == SHA
        assert resolve.call_args.args[0] == GitHubSource(owner="org", repo="repo")


def test_pinned_sha_is_resolved_and_access_is_checked() -> None:
    """A SHA goes through the same commits call as a branch: it both confirms
    the commit exists and proves the caller can read the repo."""
    provider = GitHubArchiveProvider()
    with patch(
        f"{MODULE}.resolve_github_revision",
        return_value=GitHubRevision(revision=SHA, subpath=None),
    ) as resolve:
        assert provider.resolve_commit(REPO, SHA.upper()) == SHA
    resolve.assert_called_once_with(
        GitHubSource(owner="org", repo="repo", tree_tail=(SHA.upper(),)), None
    )


def test_from_token_and_repo_ref_from_url() -> None:
    assert GitHubArchiveProvider.from_token("t")._authorization_header == "Bearer t"
    assert GitHubArchiveProvider.from_token(None)._authorization_header is None

    for source in (
        "https://github.com/org/repo",
        "https://github.com/org/repo.git",
        "org/repo",
        "git@github.com:org/repo.git",
    ):
        assert GitHubArchiveProvider.repo_ref_from_url(source) == REPO

    with pytest.raises(OnyxError):
        GitHubArchiveProvider.repo_ref_from_url("https://example.com/org/repo")


def test_stream_archive_delegates() -> None:
    provider = GitHubArchiveProvider("Bearer t")
    sink = BytesIO()
    with patch(f"{MODULE}.stream_github_archive", return_value=3) as stream:
        assert (
            provider.stream_archive(REPO, SHA, sink, max_size_bytes=10, timeout=5) == 3
        )
    stream.assert_called_once_with(
        GitHubSource(owner="org", repo="repo"),
        SHA,
        "Bearer t",
        max_size_bytes=10,
        timeout=5,
        sink=sink,
    )
