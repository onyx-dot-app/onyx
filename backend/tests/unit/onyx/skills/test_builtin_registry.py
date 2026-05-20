from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.orm import Session

from onyx.skills.registry import BuiltinSkill
from onyx.skills.registry import BuiltinSkillRegistry


def _write_skill(
    root: Path,
    slug: str,
    *,
    description: str = "Test skill",
    template: bool = False,
) -> Path:
    skill_dir = root / slug
    skill_dir.mkdir()
    skill_file = skill_dir / ("SKILL.md.template" if template else "SKILL.md")
    skill_file.write_text(
        "\n".join(
            [
                "---",
                f"name: {slug}",
                f"description: {description}",
                "---",
                "",
                f"# {slug}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return skill_dir


def test_register_rejects_duplicate_slug(tmp_path: Path) -> None:
    registry = BuiltinSkillRegistry()
    first_dir = _write_skill(tmp_path, "first")
    second_dir = _write_skill(tmp_path, "second")

    registry.register("shared-slug", first_dir)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("shared-slug", second_dir)


def test_register_rejects_invalid_slug(tmp_path: Path) -> None:
    registry = BuiltinSkillRegistry()
    skill_dir = _write_skill(tmp_path, "invalid-source")

    with pytest.raises(ValueError, match="start with a lowercase letter"):
        registry.register("Invalid_Slug", skill_dir)


def test_builtin_skill_is_frozen(tmp_path: Path) -> None:
    skill = BuiltinSkill(
        slug="builtin",
        name="Builtin",
        description="Builtin",
        source_dir=tmp_path,
        has_template=False,
    )

    with pytest.raises(ValueError, match="frozen"):
        skill.name = "Changed"

    assert skill.source == "builtin"


def test_register_rejects_missing_skill_md(tmp_path: Path) -> None:
    registry = BuiltinSkillRegistry()
    skill_dir = tmp_path / "missing-skill-md"
    skill_dir.mkdir()

    with pytest.raises(ValueError, match="SKILL.md"):
        registry.register("missing-skill-md", skill_dir)


def test_register_detects_template_metadata_source(tmp_path: Path) -> None:
    registry = BuiltinSkillRegistry()
    skill_dir = _write_skill(tmp_path, "templated", template=True)

    registry.register("templated", skill_dir)

    skill = registry.get("templated")
    assert skill is not None
    assert skill.has_template is True
    assert skill.name == "templated"


def test_reset_for_testing_clears_singleton(tmp_path: Path) -> None:
    BuiltinSkillRegistry._reset_for_testing()
    registry = BuiltinSkillRegistry.instance()
    registry.register("singleton-skill", _write_skill(tmp_path, "singleton-skill"))

    BuiltinSkillRegistry._reset_for_testing()
    fresh_registry = BuiltinSkillRegistry.instance()

    assert fresh_registry.get("singleton-skill") is None


def test_list_available_excludes_unavailable_skill(
    tmp_path: Path,
) -> None:
    registry = BuiltinSkillRegistry()
    available_dir = _write_skill(tmp_path, "available")
    unavailable_dir = _write_skill(tmp_path, "unavailable")
    db = cast(Session, object())

    registry.register("available", available_dir)
    registry.register(
        "unavailable",
        unavailable_dir,
        is_available=lambda _: False,
        unavailable_reason="Configure the provider first.",
    )

    assert [skill.slug for skill in registry.list_available(db)] == ["available"]

    unavailable = registry.get("unavailable")
    assert unavailable is not None
    assert unavailable.is_available(db) is False
    assert unavailable.unavailable_reason == "Configure the provider first."
