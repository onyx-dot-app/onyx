import re
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

SKILL_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
GITHUB_SKILL_MAX_COUNT: Final[int] = 500


class SkillMetadata(BaseModel):
    """Typed representation of Agent Skills frontmatter."""

    model_config = ConfigDict(
        extra="allow",
        frozen=True,
        populate_by_name=True,
        strict=True,
    )

    name: str
    description: str
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, str] | None = None
    allowed_tools: str | None = Field(default=None, alias="allowed-tools")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if len(value) > 64:
            raise ValueError("must be at most 64 characters")
        if not SKILL_NAME_PATTERN.fullmatch(value):
            raise ValueError(
                "must contain only lowercase letters, numbers, and single hyphens"
            )
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        if len(value) > 1024:
            raise ValueError("must be at most 1024 characters")
        return value

    @field_validator("compatibility")
    @classmethod
    def validate_compatibility(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("must not be empty when provided")
        if len(value) > 500:
            raise ValueError("must be at most 500 characters")
        return value


class SkillDocument(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    metadata: SkillMetadata
    instructions_markdown: str
    # The parsed YAML mapping that metadata was validated from.
    frontmatter: dict[str, Any]


class SkillBundleFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    size: int


class PluginFileEntry(BaseModel):
    """One file of a plugin version's bundle, as stored in file_manifest."""

    model_config = ConfigDict(frozen=True)

    path: str
    size: int
    sha256: str


def _frontmatter_string(frontmatter: dict[str, JsonValue], key: str) -> str:
    value = frontmatter.get(key)
    if not isinstance(value, str):
        raise ValueError(f"frontmatter must hold a string '{key}'")
    return value


class PluginSkillContent(BaseModel):
    """One skill in a plugin version, as written to a plugin_skill row."""

    model_config = ConfigDict(frozen=True)

    # Folder in the bundle; empty for a SKILL.md at the root.
    path: str
    # None only for a version copied from a legacy skill row.
    skill_md: str | None
    frontmatter: dict[str, JsonValue]

    @field_validator("frontmatter")
    @classmethod
    def _holds_name_and_description(
        cls, frontmatter: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        _frontmatter_string(frontmatter, "name")
        _frontmatter_string(frontmatter, "description")
        return frontmatter

    @property
    def name(self) -> str:
        return _frontmatter_string(self.frontmatter, "name")

    @property
    def description(self) -> str:
        return _frontmatter_string(self.frontmatter, "description")


class PluginVersionContent(BaseModel):
    """Everything one new plugin version stores, built from the normalized
    bundle bytes that the file store holds."""

    model_config = ConfigDict(frozen=True)

    bundle_file_id: str
    # None only for a legacy row that never had a hash or a classification.
    bundle_sha256: str | None
    is_valid: bool | None
    # Sorted by path. Covers every file in the bundle, SKILL.md included.
    # None for a version copied from a legacy skill row, whose bundle was not
    # read.
    file_manifest: list[PluginFileEntry] | None
    unpacked_size_bytes: int | None
    file_count: int | None
    skills: list[PluginSkillContent]


class CustomSkillBundleContents(BaseModel):
    model_config = ConfigDict(frozen=True)

    instructions_markdown: str
    files: list[SkillBundleFile]


class GitHubRepository(BaseModel):
    model_config = ConfigDict(frozen=True)

    owner: str
    repo: str
    revision: str
    subpath: str | None = None


class GitHubSkillBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    name: str
    description: str | None
    bundle_bytes: bytes | None
    unavailable_reason: str | None = None


class SkillUsage(BaseModel):
    """Unpacked size and file count of skills."""

    model_config = ConfigDict(frozen=True)

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


class SkillLimitRefusal(BaseModel):
    """Why a write was refused: the acting user's usage after it, and the
    write limits."""

    usage: SkillUsage
    max_bytes: int
    max_files: int


class SkillOmission(BaseModel):
    """A plugin that the run-time limit left out of a sandbox."""

    model_config = ConfigDict(frozen=True)

    plugin_id: UUID
    name: str
    # Size and file count of the version the user runs.
    bytes: int
    files: int
    # The limit it would break.
    reason: Literal["bytes", "files"]


class SkillLimitNotice(BaseModel):
    """The plugins the run-time limit left out, and that limit."""

    skills: list[SkillOmission]
    max_bytes: int
    max_files: int


class SandboxSkillsState(BaseModel):
    """The skill content a sandbox got: its hash and the plugins the run-time
    skill limit left out of it."""

    model_config = ConfigDict(frozen=True)

    skills_hash: str | None
    omissions: tuple[SkillOmission, ...]


class UserPastWriteLimit(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    email: str
    usage: SkillUsage
    # Plugins the last push left out of the user's sandbox.
    skills_not_loaded: int
