import re
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

import yaml
from pydantic import BaseModel
from pydantic import ConfigDict
from sqlalchemy.orm import Session

_SLUG_REGEX = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


def _always_available(_: Session) -> bool:
    return True


class BuiltinSkill(BaseModel):
    """In-memory entry for an on-disk built-in skill."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    slug: str
    source_dir: Path
    name: str
    description: str
    has_template: bool
    is_available: Callable[[Session], bool] = _always_available
    unavailable_reason: str | None = None
    configure_url: str | None = None


def _validate_slug(slug: str) -> None:
    if not _SLUG_REGEX.fullmatch(slug):
        raise ValueError(
            f"Skill slug must match ^[a-z][a-z0-9-]{{0,63}}$; got {slug!r}"
        )


def _skill_metadata_path(source_dir: Path) -> tuple[Path, bool]:
    skill_md_path = source_dir / "SKILL.md"
    template_path = source_dir / "SKILL.md.template"

    if template_path.exists():
        return template_path, True

    if skill_md_path.exists():
        return skill_md_path, False

    raise ValueError(
        f"Built-in skill source directory {source_dir} must contain "
        "SKILL.md or SKILL.md.template"
    )


def _read_frontmatter(path: Path) -> dict[str, object]:
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path} must start with YAML frontmatter")

    frontmatter_lines: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            parsed = yaml.safe_load("\n".join(frontmatter_lines)) or {}
            if not isinstance(parsed, dict):
                raise ValueError(f"{path} frontmatter must be a mapping")
            return parsed
        frontmatter_lines.append(line)

    raise ValueError(f"{path} frontmatter is missing closing --- delimiter")


def _read_metadata(source_dir: Path) -> tuple[str, str, bool]:
    metadata_path, has_template = _skill_metadata_path(source_dir)
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

    def __init__(self) -> None:
        self._skills: dict[str, BuiltinSkill] = {}

    @classmethod
    def instance(cls) -> "BuiltinSkillRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset_for_testing(cls) -> None:
        cls._instance = None

    def register(
        self,
        slug: str,
        source_dir: Path,
        is_available: Callable[[Session], bool] = _always_available,
        unavailable_reason: str | None = None,
        configure_url: str | None = None,
    ) -> None:
        _validate_slug(slug)

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
            configure_url=configure_url,
        )

    def list_all(self) -> list[BuiltinSkill]:
        return list(self._skills.values())

    def list_satisfied(self, db: Session) -> list[BuiltinSkill]:
        return [skill for skill in self.list_all() if skill.is_available(db)]

    def get(self, slug: str) -> BuiltinSkill | None:
        return self._skills.get(slug)

    def reserved_slugs(self) -> set[str]:
        return set(self._skills)
