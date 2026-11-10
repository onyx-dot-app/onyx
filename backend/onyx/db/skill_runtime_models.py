from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SkillRuntimeLimit(str, Enum):
    BYTES = "bytes"
    FILES = "files"
    DIRECTORIES = "directories"
    PATHS = "paths"


class SkillRuntimeOmission(BaseModel):
    """A whole Skill left out because it did not fit the runtime limit.

    Stored on the sandbox with the content that was delivered to it.
    """

    model_config = ConfigDict(frozen=True)

    skill_id: UUID
    name: str
    charged_bytes: int
    file_count: int
    # Bytes are checked first when both limits fail.
    failed_limit: SkillRuntimeLimit
