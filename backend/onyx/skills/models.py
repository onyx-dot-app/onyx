import re
from enum import Enum
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    computed_field,
    field_validator,
)

from onyx.utils.url import McpUrlProblem

SKILL_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKILL_NAME_MAX_LENGTH: Final = 64
SkillName = Annotated[
    str, Field(pattern=SKILL_NAME_PATTERN, max_length=SKILL_NAME_MAX_LENGTH)
]
GITHUB_SKILL_MAX_COUNT: Final[int] = 500
# Frontmatter fields Onyx does not read. A bad value is dropped, not refused.
UNUSED_FRONTMATTER_FIELDS: Final = frozenset(
    {"license", "compatibility", "metadata", "allowed-tools"}
)
_BIDI_CONTROLS: Final[re.Pattern[str]] = re.compile("[\u202a-\u202e\u2066-\u2069]")


def strip_bidi_controls(value: str) -> str:
    """Remove the bidi embedding, override and isolate characters, which can
    make shown text read differently from what it holds."""
    return _BIDI_CONTROLS.sub("", value)


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
    # Onyx does not read these two. Claude Code accepts a list for
    # allowed-tools and nested values in metadata.
    metadata: dict[str, Any] | None = None
    allowed_tools: str | list[str] | None = Field(default=None, alias="allowed-tools")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if len(value) > SKILL_NAME_MAX_LENGTH:
            raise ValueError(f"must be at most {SKILL_NAME_MAX_LENGTH} characters")
        if not SKILL_NAME_PATTERN.fullmatch(value):
            raise ValueError(
                "must contain only lowercase letters, numbers, and single hyphens"
            )
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        value = strip_bidi_controls(value)
        if not value.strip():
            raise ValueError("must not be empty")
        if len(value) > 1024:
            raise ValueError("must be at most 1024 characters")
        if "\x00" in value:
            raise ValueError("must not contain a NUL character")
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


class PluginUnusedPart(str, Enum):
    COMMANDS = "commands"
    AGENTS = "agents"
    HOOKS = "hooks"
    LSP_SERVERS = "lsp_servers"
    OUTPUT_STYLES = "output_styles"
    BIN = "bin"
    THEMES = "themes"
    MONITORS = "monitors"


class PluginAuthor(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str | None = None
    email: str | None = None
    url: str | None = None


class PluginManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    version: str | None = None
    description: str | None = None
    author: PluginAuthor | None = None
    homepage: str | None = None
    repository: str | None = None
    license: str | None = None
    keywords: list[str] = Field(default_factory=list)
    unused_parts: list[PluginUnusedPart] = Field(default_factory=list)


MCP_URL_TRANSPORTS: Final = frozenset({"http", "streamable-http", "sse"})


class PluginNeed(BaseModel):
    """A need names a server by URL and never refers to an integration row."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["mcp"] = "mcp"
    name: str
    url: str | None
    transport: str | None
    # Why the plugin's URL was dropped. None when it had no URL.
    url_problem: McpUrlProblem | None = None

    @computed_field
    @property
    def supported(self) -> bool:
        return self.url is not None and self.transport in MCP_URL_TRANSPORTS


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
    manifest: PluginManifest | None = None
    needs: list[PluginNeed] | None = None


class PluginBundleSkill(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: PluginSkillContent
    warnings: list[str]


class PluginBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: bytes
    manifest: PluginManifest
    skills: list[PluginBundleSkill]
    needs: list[PluginNeed]
    warnings: list[str]


class BundleLayout(BaseModel):
    model_config = ConfigDict(frozen=True)

    markers: tuple[str, ...]
    missing_detail: str
    outside_detail: str


class CustomSkillBundleContents(BaseModel):
    model_config = ConfigDict(frozen=True)

    instructions_markdown: str
    files: list[SkillBundleFile]


class ChatSkill(BaseModel):
    """A skill that chat offers the user: a custom skill at the version the
    user runs, or a built-in, whose ``version_id`` is its Skill row id. Each
    description is one line: runs of whitespace become one space."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    # `metadata.short-description` in the frontmatter, which the catalog
    # prefers. None when it is missing or blank.
    short_description: str | None = None
    version_id: UUID
    path: str = ""
    built_in_skill_id: str | None = None
    # The plugin of a custom skill. None for a built-in.
    plugin_id: UUID | None = None

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("short_description")
    @classmethod
    def normalize_short_description(cls, value: str | None) -> str | None:
        return (" ".join(value.split()) or None) if value is not None else None


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


class ChatSkillFiles(BaseModel):
    """One chat skill's files, each under `<name>/`, and the key of that
    version of them."""

    model_config = ConfigDict(frozen=True)

    version: str
    files: dict[str, bytes]
