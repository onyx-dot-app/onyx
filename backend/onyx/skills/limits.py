"""Per-user skill limits.

A user's own write may not move them from within the write limits to past
them. The run-time limits are larger: a user past the write limits, for
example after a group join, still gets every plugin that fits in them
(``onyx.skills.push``).
"""

from typing import Final

from onyx.server.features.build.sandbox.image.sandbox_daemon.extract import (
    MAX_BUNDLE_BYTES,
)
from onyx.skills.models import SkillLimitNotice, SkillOmission, SkillUsage

SKILL_WRITE_MAX_BYTES: Final[int] = 500 * 1024 * 1024
SKILL_WRITE_MAX_FILES: Final[int] = 5_000

# A 1 GB sandbox disk held 1,000 MB of skills. The spare 100 MB also holds
# the disk blocks of up to 10,000 small files. It is the push transport cap
# too, so the sandbox daemon's constant is the one source.
SKILL_RUNTIME_MAX_BYTES: Final[int] = MAX_BUNDLE_BYTES
SKILL_RUNTIME_MAX_FILES: Final[int] = 10_000


def is_over_write_limit(usage: SkillUsage) -> bool:
    return usage.bytes > SKILL_WRITE_MAX_BYTES or usage.files > SKILL_WRITE_MAX_FILES


def runtime_limit_notice(skills: list[SkillOmission]) -> SkillLimitNotice | None:
    if not skills:
        return None
    return SkillLimitNotice(
        skills=skills,
        max_bytes=SKILL_RUNTIME_MAX_BYTES,
        max_files=SKILL_RUNTIME_MAX_FILES,
    )
