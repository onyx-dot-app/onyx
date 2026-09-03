"""Provider-agnostic identity of a repository revision and of a local archive."""

import hashlib
import string
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

# What GitHub and GitLab allow in a namespace or repository name. Excludes
# ":" and "/", the separators `key` is built from, so no two repositories can
# produce the same cache key.
_ALLOWED_SEGMENT_CHARS = frozenset(string.ascii_letters + string.digits + "._-")


def _is_plain_name(segment: str) -> bool:
    """A single path segment a hosting provider could actually issue.

    Rejects the empty string and the traversal names ("." / ".."), which would
    escape the key space, and any character outside the allowed set, which
    could alias another repo once the key becomes a file-store id.
    """
    if not segment or not segment.strip("."):
        return False
    return _ALLOWED_SEGMENT_CHARS.issuperset(segment)


class RepoRef(BaseModel):
    """A repository on a hosting provider."""

    model_config = ConfigDict(frozen=True)

    provider: str  # e.g. "github"
    host: str  # e.g. "github.com"; separates self-hosted instances
    owner: str  # namespace path: "org" or "group/subgroup"
    name: str

    @field_validator("provider", "host", "name")
    @classmethod
    def _validate_segment(cls, value: str, info: ValidationInfo) -> str:
        """These are single segments of a cache key. Raised as a pydantic
        ValidationError; callers that build a RepoRef from user input convert
        it to an OnyxError at their boundary."""
        if not _is_plain_name(value):
            raise ValueError(f"Invalid repo {info.field_name}: {value!r}")
        return value

    @field_validator("owner")
    @classmethod
    def _validate_owner(cls, value: str) -> str:
        """`owner` is the one field that may be a path — GitLab subgroups."""
        if not all(_is_plain_name(segment) for segment in value.split("/")):
            raise ValueError(f"Invalid repo owner: {value!r}")
        return value

    @property
    def key_prefix(self) -> str:
        """Cache-key prefix shared by every revision of this repo.

        ":" separates the fields because no field may contain one, and `owner`
        may contain "/". Joining on "/" alone would let owner="a/b" name="c"
        and owner="a" name="b/c" share a key.
        """
        return f"{self.provider}:{self.host}:{self.owner}:{self.name}:"

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
