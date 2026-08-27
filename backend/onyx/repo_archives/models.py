"""Provider-agnostic identity of a repository revision and of a local archive."""

import hashlib
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

# What GitHub and GitLab allow in a namespace or repository name. Anything
# else could alias another repo once `key_prefix` becomes a file-store id
# prefix, or escape the key space entirely.
_PATH_SEGMENT = re.compile(r"(?!\.+\Z)[A-Za-z0-9._-]+\Z")


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
        """`owner` and `name` become path segments of a cache key, so every
        "/"-separated segment must be a plain name."""
        if not all(_PATH_SEGMENT.match(segment) for segment in value.split("/")):
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
