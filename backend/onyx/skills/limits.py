"""Per-user Skill limits and their public error contract.

Writes keep each affected user within ``SKILL_WRITE_MAX_BYTES`` and
``SKILL_WRITE_MAX_FILES``. The runtime limit in ``onyx.skills.push`` is larger
and handles users who are already over, such as after a group join.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Final
from uuid import UUID

from pydantic import BaseModel, RootModel

from onyx.skills.bundle import DEFAULT_MAX_FILE_COUNT, DEFAULT_TOTAL_MAX_BYTES

SKILL_WRITE_MAX_BYTES: Final[int] = 500 * 1024 * 1024
SKILL_WRITE_MAX_FILES: Final[int] = 5_000
# A current version without metadata counts as the largest bundle a stored read
# accepts, and as the upload file-count limit, until repair measures it.
UNKNOWN_SKILL_BYTES: Final[int] = DEFAULT_TOTAL_MAX_BYTES
UNKNOWN_SKILL_FILES: Final[int] = DEFAULT_MAX_FILE_COUNT


class SkillLimit(str, Enum):
    BYTES = "bytes"
    FILES = "files"


@dataclass(frozen=True)
class SkillFootprint:
    bytes: int
    files: int


@dataclass(frozen=True)
class SkillUsage:
    """Unpacked totals of the Skills a user gets, from current-version metadata."""

    bytes: int = 0
    files: int = 0
    unknown_skill_count: int = 0

    @property
    def charged_bytes(self) -> int:
        return self.bytes + self.unknown_skill_count * UNKNOWN_SKILL_BYTES

    @property
    def charged_files(self) -> int:
        return self.files + self.unknown_skill_count * UNKNOWN_SKILL_FILES

    def __add__(self, other: "SkillUsage") -> "SkillUsage":
        return SkillUsage(
            bytes=self.bytes + other.bytes,
            files=self.files + other.files,
            unknown_skill_count=self.unknown_skill_count + other.unknown_skill_count,
        )

    def __sub__(self, other: "SkillUsage") -> "SkillUsage":
        return SkillUsage(
            bytes=self.bytes - other.bytes,
            files=self.files - other.files,
            unknown_skill_count=self.unknown_skill_count - other.unknown_skill_count,
        )


def failed_skill_limit(after: SkillUsage, before: SkillUsage) -> SkillLimit | None:
    """The limit a change breaks; a user already over may stay over without growing."""
    if (
        after.charged_bytes > SKILL_WRITE_MAX_BYTES
        and after.charged_bytes > before.charged_bytes
    ):
        return SkillLimit.BYTES
    if (
        after.charged_files > SKILL_WRITE_MAX_FILES
        and after.charged_files > before.charged_files
    ):
        return SkillLimit.FILES
    return None


@dataclass(frozen=True)
class SkillLimitBaseline:
    """Usage captured under user locks before a write.

    ``user_ids`` limits the check to those users. Otherwise the check covers
    everyone who can reach ``skill_ids`` before or after the write. A user who
    could not reach them before gets a baseline without them.

    A write changes only ``skill_ids``. A total sums one winner per name, so
    only the names of those Skills can change it. ``before`` holds each
    user's usage from Skills with ``names``, not the full total.
    """

    skill_ids: frozenset[UUID]
    user_ids: frozenset[UUID] | None = None
    names: frozenset[str] = frozenset()
    before: dict[UUID, SkillUsage] = field(default_factory=dict)


class SkillUsageSummary(BaseModel):
    bytes: int
    files: int
    unknown_skill_count: int
    charged_bytes: int
    charged_files: int
    max_bytes: int = SKILL_WRITE_MAX_BYTES
    max_files: int = SKILL_WRITE_MAX_FILES

    @classmethod
    def from_usage(cls, usage: SkillUsage) -> "SkillUsageSummary":
        return cls(
            bytes=usage.bytes,
            files=usage.files,
            unknown_skill_count=usage.unknown_skill_count,
            charged_bytes=usage.charged_bytes,
            charged_files=usage.charged_files,
        )


class SkillLimitViolation(BaseModel):
    """Body field ``skill_limit`` of a 413 ``PAYLOAD_TOO_LARGE`` Skill write.

    ``usage`` is the requesting user's proposed usage when that user goes over.
    """

    failed_limit: SkillLimit
    affected_user_count: int
    usage: SkillUsageSummary | None = None


# The reason in ``Marketplace.blocked_entries`` for an entry the limit blocked.
SKILL_LIMIT_BLOCK_REASON: Final[str] = "skill limit"


class SkillLimitBlocks(RootModel[dict[str, SkillLimitViolation]]):
    """Marketplace entry keys that the last sync blocked for the limit."""

    root: dict[str, SkillLimitViolation] = {}
