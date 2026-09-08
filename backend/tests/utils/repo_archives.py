"""Test doubles for onyx.repo_archives: a tarball builder and an in-memory
provider, so tests need no network and no patching of provider internals."""

import io
import tarfile
from collections.abc import Sequence
from typing import BinaryIO

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.repo_archives.models import RepoRef, RepoRevision
from onyx.utils.github import GITHUB_COMMIT_SHA_PATTERN

TEST_REPO = RepoRef(provider="test", host="test.local", owner="test-org", name="repo")


def make_repo_tarball(
    files: dict[str, bytes],
    top_dir: str | None = "org-repo-abc1234",
    *,
    extra_members: Sequence[tarfile.TarInfo] = (),
) -> bytes:
    """A repo-archive-shaped tar.gz: contents wrapped in one top-level dir.

    `top_dir=None` builds a flat archive. `extra_members` are added verbatim
    and carry no data, for directories, symlinks, and other non-file entries.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for member in extra_members:
            tar.addfile(member)
        for path, content in files.items():
            info = tarfile.TarInfo(name=f"{top_dir}/{path}" if top_dir else path)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def revision(commit_sha: str, repo: RepoRef = TEST_REPO) -> RepoRevision:
    return RepoRevision(repo=repo, commit_sha=commit_sha)


class FakeArchiveProvider:
    """In-memory RepoArchiveProvider.

    `refs` maps ref names (None = default branch) to commit SHAs; `archives`
    maps the revision string handed to `stream_archive` to tarball bytes.
    Records every resolution and download for assertions.
    """

    def __init__(
        self,
        archives: dict[str, bytes],
        refs: dict[str | None, str] | None = None,
        *,
        authenticated: bool = True,
        resolve_error: OnyxError | None = None,
    ) -> None:
        self.archives = archives
        self.refs = refs or {}
        self._authenticated = authenticated
        self.resolve_error = resolve_error
        self.resolve_calls = 0
        self.downloads: list[str] = []

    @property
    def authenticated(self) -> bool:
        return self._authenticated

    def repo_ref(self, owner: str, name: str) -> RepoRef:
        return RepoRef(
            provider=TEST_REPO.provider, host=TEST_REPO.host, owner=owner, name=name
        )

    def resolve_commit(self, repo: RepoRef, ref: str | None) -> str:  # noqa: ARG002
        self.resolve_calls += 1
        if self.resolve_error is not None:
            raise self.resolve_error
        if ref and GITHUB_COMMIT_SHA_PATTERN.fullmatch(ref):
            return ref.lower()
        if ref not in self.refs:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, f"unknown ref {ref}")
        return self.refs[ref]

    def stream_archive(
        self,
        repo: RepoRef,  # noqa: ARG002
        revision: str,
        sink: BinaryIO,
        *,
        max_size_bytes: int,
        timeout: float | tuple[float, float],  # noqa: ARG002
    ) -> int:
        self.downloads.append(revision)
        data = self.archives[revision]
        if len(data) > max_size_bytes:
            raise OnyxError(OnyxErrorCode.PAYLOAD_TOO_LARGE, "too large")
        return sink.write(data)
