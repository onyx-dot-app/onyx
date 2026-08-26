from dataclasses import replace
from typing import BinaryIO

from onyx.repo_archives.models import RepoRef
from onyx.utils.github import (
    GITHUB_COMMIT_SHA_PATTERN,
    GitHubSource,
    resolve_github_revision,
    stream_github_archive,
)


class GitHubArchiveProvider:
    """RepoArchiveProvider for github.com."""

    PROVIDER = "github"
    HOST = "github.com"

    def __init__(self, authorization_header: str | None = None) -> None:
        self._authorization_header = authorization_header

    @classmethod
    def repo_ref(cls, owner: str, name: str) -> RepoRef:
        return RepoRef(provider=cls.PROVIDER, host=cls.HOST, owner=owner, name=name)

    @property
    def authenticated(self) -> bool:
        return self._authorization_header is not None

    def resolve_commit(self, repo: RepoRef, ref: str | None) -> str:
        source = GitHubSource(owner=repo.owner, repo=repo.name)
        if ref and GITHUB_COMMIT_SHA_PATTERN.fullmatch(ref):
            # A pinned SHA needs no resolution, but one authenticated repo
            # call still runs so a caller without access cannot read cached
            # source. On failure the download path enforces access itself.
            resolve_github_revision(source, self._authorization_header)
            return ref.lower()
        if ref:
            source = replace(source, tree_tail=(ref,))
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
            GitHubSource(owner=repo.owner, repo=repo.name),
            revision,
            self._authorization_header,
            max_size_bytes=max_size_bytes,
            timeout=timeout,
            sink=sink,
        )
