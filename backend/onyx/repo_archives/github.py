from typing import BinaryIO

from onyx.repo_archives.models import RepoRef
from onyx.utils.github import (
    GitHubSource,
    parse_github_source,
    resolve_github_revision,
    stream_github_archive,
)


def _source(repo: RepoRef, tree_tail: tuple[str, ...] = ()) -> GitHubSource:
    return GitHubSource(owner=repo.owner, repo=repo.name, tree_tail=tree_tail)


class GitHubArchiveProvider:
    """RepoArchiveProvider for github.com."""

    PROVIDER = "github"
    HOST = "github.com"

    def __init__(self, authorization_header: str | None = None) -> None:
        self._authorization_header = authorization_header

    @classmethod
    def from_token(cls, token: str | None) -> "GitHubArchiveProvider":
        """Provider for a GitHub access token; anonymous when None."""
        return cls(f"Bearer {token}" if token else None)

    @classmethod
    def repo_ref(cls, owner: str, name: str) -> RepoRef:
        return RepoRef(provider=cls.PROVIDER, host=cls.HOST, owner=owner, name=name)

    @classmethod
    def repo_ref_from_url(cls, repo_url: str) -> RepoRef:
        """Identity of the repo named by a URL, `owner/repo`, or SSH remote.
        Raises OnyxError when the source cannot be parsed."""
        source = parse_github_source(repo_url, allow_ssh=True)
        return cls.repo_ref(source.owner, source.repo)

    @property
    def authenticated(self) -> bool:
        return self._authorization_header is not None

    def resolve_commit(self, repo: RepoRef, ref: str | None) -> str:
        # GitHub's commits endpoint accepts a branch, tag, or SHA, so one call
        # both resolves `ref` and proves the caller can access the repo.
        source = _source(repo, tree_tail=(ref,) if ref else ())
        return resolve_github_revision(source, self._authorization_header).revision

    def stream_archive(
        self,
        repo: RepoRef,
        revision: str,
        sink: BinaryIO,
        *,
        max_size_bytes: int,
        timeout: float | tuple[float, float],
    ) -> int:
        return stream_github_archive(
            _source(repo),
            revision,
            self._authorization_header,
            max_size_bytes=max_size_bytes,
            timeout=timeout,
            sink=sink,
        )
