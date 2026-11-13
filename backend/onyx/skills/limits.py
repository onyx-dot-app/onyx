"""Per-user skill limits for writes.

A user's own write may not move them from within these limits to past them.
"""

from typing import Final

from onyx.skills.models import SkillUsage

SKILL_WRITE_MAX_BYTES: Final[int] = 500 * 1024 * 1024
SKILL_WRITE_MAX_FILES: Final[int] = 5_000


def is_over_write_limit(usage: SkillUsage) -> bool:
    return usage.bytes > SKILL_WRITE_MAX_BYTES or usage.files > SKILL_WRITE_MAX_FILES
