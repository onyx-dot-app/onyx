import re
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import ClassVar
from typing import Literal
from uuid import UUID

import yaml
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import field_validator
from sqlalchemy.orm import Session

_SLUG_REGEX = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_FRONTMATTER_REGEX = re.compile(
    r"\A---[ \t]*\r?\n(?P<frontmatter>.*?)(?:\r?\n)---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)
_DEFAULT_IS_AVAILABLE: Callable[[Session], bool] = lambda _: True  # noqa: E731
_SLUG_ERROR = (
    "Skill slug must start with a lowercase letter, contain only lowercase "
    "letters, numbers, and hyphens, and be at most 64 characters."
)


class Skill(BaseModel):
    """Common skill metadata shared by built-in and custom skill views."""

    slug: str
    name: str
    description: str

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, slug: str) -> str:
        if not _SLUG_REGEX.fullmatch(slug):
            raise ValueError(_SLUG_ERROR)
        return slug


class BuiltinSkill(Skill):
    """In-memory entry for an on-disk built-in skill."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    source: Literal["builtin"] = "builtin"
    source_dir: Path
    has_template: bool
    is_available: Callable[[Session], bool] = _DEFAULT_IS_AVAILABLE
    unavailable_reason: str | None = None


class CustomSkill(Skill):
    """DB-backed skill metadata needed by skill consumers."""

    source: Literal["custom"] = "custom"
    id: UUID
    bundle_file_id: str
    bundle_sha256: str
    is_public: bool
    enabled: bool


def _select_skill_definition_path(source_dir: Path) -> tuple[Path, bool]:
    skill_md_path = source_dir / "SKILL.md"
    template_path = source_dir / "SKILL.md.template"

    if template_path.exists():
        return template_path, True

    if skill_md_path.exists():
        return skill_md_path, False

    raise ValueError(
        f"Built-in skill source directory {source_dir} must contain "
        "either SKILL.md or SKILL.md.template"
    )


def _read_frontmatter(path: Path) -> dict[str, object]:
    content = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_REGEX.match(content)
    if match is None:
        raise ValueError(
            f"{path} must start with YAML frontmatter delimited by two --- lines"
        )

    parsed = yaml.safe_load(match.group("frontmatter")) or {}
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} frontmatter must be a mapping")
    return parsed


def _read_metadata(source_dir: Path) -> tuple[str, str, bool]:
    metadata_path, has_template = _select_skill_definition_path(source_dir)
    frontmatter = _read_frontmatter(metadata_path)

    name = frontmatter.get("name")
    description = frontmatter.get("description")

    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{metadata_path} frontmatter must include name")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"{metadata_path} frontmatter must include description")

    return name, description, has_template


class BuiltinSkillRegistry:
    """Process-wide registry populated with on-disk built-in skills at boot."""

    _instance: ClassVar["BuiltinSkillRegistry | None"] = None
    _instance_lock: ClassVar[Lock] = Lock()

    def __init__(self) -> None:
        self._skills: dict[str, BuiltinSkill] = {}

    @classmethod
    def instance(cls) -> "BuiltinSkillRegistry":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset_for_testing(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    def register(
        self,
        slug: str,
        source_dir: Path,
        is_available: Callable[[Session], bool] = _DEFAULT_IS_AVAILABLE,
        unavailable_reason: str | None = None,
    ) -> None:
        if slug in self._skills:
            raise ValueError(f"Built-in skill {slug!r} is already registered")

        resolved_source_dir = source_dir.resolve()
        if not resolved_source_dir.is_dir():
            raise ValueError(
                f"Built-in skill source directory {resolved_source_dir} does not exist"
            )

        name, description, has_template = _read_metadata(resolved_source_dir)
        self._skills[slug] = BuiltinSkill(
            slug=slug,
            source_dir=resolved_source_dir,
            name=name,
            description=description,
            has_template=has_template,
            is_available=is_available,
            unavailable_reason=unavailable_reason,
        )

    def list_all(self) -> list[BuiltinSkill]:
        return list(self._skills.values())

    def list_available(self, db: Session) -> list[BuiltinSkill]:
        return [skill for skill in self.list_all() if skill.is_available(db)]

    def get(self, slug: str) -> BuiltinSkill | None:
        return self._skills.get(slug)

    def reserved_slugs(self) -> set[str]:
        return set(self._skills)
