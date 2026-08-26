"""Provider-agnostic identity of a repository revision and of a local archive."""

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

# Segments that would let one repo alias another once `key_prefix` is used as
# a file-store id prefix, or that escape the key space entirely.
_REJECTED_SEGMENTS = frozenset({"", ".", ".."})


class RepoRef(BaseModel):
    """A repository on a hosting provider."""

    model_config = ConfigDict(frozen=True)

    provider: str  # e.g. "github"
    host: str  # e.g. "github.com"; separates self-hosted instances
    owner: str  # namespace path: "org" or "group/subgroup"
    name: str

    @field_validator("owner", "name")
    @classmethod
    def _validate_path_part(cls, value: str, info: ValidationInfo) -> str:
        """`owner` and `name` become path segments of a cache key, so reject
        empty values, leading/trailing "/", and "." / ".." segments."""
        if any(segment in _REJECTED_SEGMENTS for segment in value.split("/")):
            raise ValueError(f"Invalid repo {info.field_name}: {value!r}")
        return value

    @property
    def key_prefix(self) -> str:
        """Cache-key prefix shared by every revision of this repo."""
        return f"{self.provider}/{self.host}/{self.owner}/{self.name}/"

    @property
    def display(self) -> str:
        return f"{self.owner}/{self.name}"


class RepoRevision(BaseModel):
    """A repository pinned to an immutable commit. The cache key of both the
    tarball cache and the local snapshot cache."""

    model_config = ConfigDict(frozen=True)

    repo: RepoRef
    commit_sha: str

    @property
    def key(self) -> str:
        return f"{self.repo.key_prefix}{self.commit_sha}"

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.key.encode()).hexdigest()[:32]


class RepoArchive(BaseModel):
    """A repository tar.gz on local disk."""

    # Exists only inside the `open_*_archive` block that produced it.
    path: Path
    size: int
    # None when the ref could not be resolved and the archive was fetched
    # directly for the requested ref, uncached.
    revision: RepoRevision | None
