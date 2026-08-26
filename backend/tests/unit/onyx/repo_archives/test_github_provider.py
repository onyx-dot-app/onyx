from io import BytesIO
from unittest.mock import patch

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


def test_pinned_sha_is_kept_but_access_is_checked() -> None:
    provider = GitHubArchiveProvider()
    with patch(f"{MODULE}.resolve_github_revision") as resolve:
        assert provider.resolve_commit(REPO, SHA.upper()) == SHA
    resolve.assert_called_once_with(GitHubSource(owner="org", repo="repo"), None)


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
