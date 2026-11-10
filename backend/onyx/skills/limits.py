"""Per-user Skill limits.

Writes keep each affected user within ``SKILL_WRITE_MAX_BYTES`` and
``SKILL_WRITE_MAX_FILES``. The runtime limit in ``onyx.skills.push`` is larger
and handles users who are already over, such as after a group join.
"""

from dataclasses import dataclass
from typing import Final

from onyx.skills.bundle import DEFAULT_MAX_FILE_COUNT, DEFAULT_TOTAL_MAX_BYTES

SKILL_WRITE_MAX_BYTES: Final[int] = 500 * 1024 * 1024
SKILL_WRITE_MAX_FILES: Final[int] = 5_000
# A current version without metadata counts as the largest bundle a stored read
# accepts, and as the upload file-count limit, until repair measures it.
UNKNOWN_SKILL_BYTES: Final[int] = DEFAULT_TOTAL_MAX_BYTES
UNKNOWN_SKILL_FILES: Final[int] = DEFAULT_MAX_FILE_COUNT


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
