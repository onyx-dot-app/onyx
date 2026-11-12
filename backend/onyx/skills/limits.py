"""Per-user skill limits.

A write may not move an active user from within the write limits to past
them. The run-time limits are larger: a user past the write limits, for
example after a group join, still gets every plugin that fits in them
(``onyx.skills.push``).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

SKILL_WRITE_MAX_BYTES: Final[int] = 500 * 1024 * 1024
SKILL_WRITE_MAX_FILES: Final[int] = 5_000

# A 1 GB sandbox disk held 1,000 MB of skills; this keeps about 110 MB spare.
SKILL_RUNTIME_MAX_BYTES: Final[int] = 900 * 1024 * 1024
SKILL_RUNTIME_MAX_FILES: Final[int] = 10_000
# The disk gives each file at least one 4 KB block.
SKILL_MIN_FILE_BYTES: Final[int] = 4096


def charged_file_bytes(size: int) -> int:
    return max(size, SKILL_MIN_FILE_BYTES)


@dataclass(frozen=True)
class SkillUsage:
    """Size and file count of skills. For the run-time limit, ``bytes`` is
    the charged size (each file at least 4 KB)."""

    bytes: int = 0
    files: int = 0

    def __add__(self, other: "SkillUsage") -> "SkillUsage":
        return SkillUsage(
            bytes=self.bytes + other.bytes, files=self.files + other.files
        )

    def __sub__(self, other: "SkillUsage") -> "SkillUsage":
        return SkillUsage(
            bytes=self.bytes - other.bytes, files=self.files - other.files
        )

    def grew_from(self, other: "SkillUsage") -> bool:
        return self.bytes > other.bytes or self.files > other.files

    @property
    def is_over_write_limit(self) -> bool:
        return self.bytes > SKILL_WRITE_MAX_BYTES or self.files > SKILL_WRITE_MAX_FILES


class KeepGroup(IntEnum):
    """Run-time keep order: a lower group stays first."""

    BUILT_IN = 0
    REQUIRED = 1
    TURNED_ON = 2
    INSTALLED_BY_DEFAULT = 3


_OLDEST: Final[datetime] = datetime.min.replace(tzinfo=timezone.utc)


def runtime_keep_key(
    group: KeepGroup, order_time: datetime | None, plugin_id: UUID
) -> tuple[int, float, UUID]:
    """Sort key of the run-time keep order: the group, then the most recent
    time first (empty is oldest), then the plugin id."""
    return (group, -(order_time or _OLDEST).timestamp(), plugin_id)


class SkillOmission(BaseModel):
    """A plugin that a skill limit left out: out of a sandbox (run-time
    limit) or turned off at app connect (write limit)."""

    model_config = ConfigDict(frozen=True)

    plugin_id: UUID
    name: str
    # Size and file count of the version the user runs (charged size for the
    # run-time limit).
    bytes: int
    files: int
    # The limit it would break.
    reason: Literal["bytes", "files"]


class SkillLimitNotice(BaseModel):
    """The plugins a skill limit left out, and that limit."""

    skills: list[SkillOmission]
    max_bytes: int
    max_files: int


class SkillUsageModel(BaseModel):
    bytes: int
    files: int


class SkillLimitRefusal(BaseModel):
    """Why a write was refused: the number of users it puts past the write
    limits, and the acting user's usage after it when they are one of them."""

    users_over: int
    usage: SkillUsageModel | None
    max_bytes: int
    max_files: int


def write_limit_notice(skills: list[SkillOmission]) -> SkillLimitNotice | None:
    if not skills:
        return None
    return SkillLimitNotice(
        skills=skills, max_bytes=SKILL_WRITE_MAX_BYTES, max_files=SKILL_WRITE_MAX_FILES
    )


def runtime_limit_notice(skills: list[SkillOmission]) -> SkillLimitNotice | None:
    if not skills:
        return None
    return SkillLimitNotice(
        skills=skills,
        max_bytes=SKILL_RUNTIME_MAX_BYTES,
        max_files=SKILL_RUNTIME_MAX_FILES,
    )


def runtime_omission_reason(
    used: SkillUsage, usage: SkillUsage
) -> Literal["bytes", "files"] | None:
    """Why ``usage`` does not fit next to ``used``, or None when it fits."""
    total = used + usage
    if total.bytes > SKILL_RUNTIME_MAX_BYTES:
        return "bytes"
    if total.files > SKILL_RUNTIME_MAX_FILES:
        return "files"
    return None
