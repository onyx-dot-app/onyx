from typing import BinaryIO, Protocol

from onyx.repo_archives.models import RepoRef


class RepoArchiveProvider(Protocol):
    """Source of repository tarballs for one hosting provider.

    Implementations raise OnyxError for provider failures (authentication,
    not found, rate limit, archive too large). Archives wrap their contents
    in one top-level directory, as GitHub and GitLab archives do.
    """

    @property
    def authenticated(self) -> bool: ...

    def repo_ref(self, owner: str, name: str) -> RepoRef:
        """Identity of a repository on this provider (and host)."""
        ...

    def resolve_commit(self, repo: RepoRef, ref: str | None) -> str:
        """Full commit SHA that `ref` (branch, tag, or SHA; None for the
        default branch) points at now.

        Must confirm the caller can access `repo` even when `ref` is already
        a SHA: the result unlocks cached archives of that repo.
        """
        ...

    def stream_archive(
        self,
        repo: RepoRef,
        revision: str,
        sink: BinaryIO,
        *,
        max_size_bytes: int,
        timeout: float | tuple[float, float],
    ) -> int:
        """Write the tar.gz of `repo` at `revision` to `sink`; return the
        number of bytes written."""
        ...
