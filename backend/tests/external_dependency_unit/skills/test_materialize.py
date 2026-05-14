from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from onyx.skills.materialize import materialize_skills
from onyx.skills.registry import BuiltinSkillRegistry


@pytest.fixture(autouse=True)
def _reset_registry() -> Generator[None, None, None]:
    BuiltinSkillRegistry._reset_for_testing()
    yield
    BuiltinSkillRegistry._reset_for_testing()


def test_materialize_creates_symlinks_and_manifest(
    tmp_path: Path, db_session: Session
) -> None:
    builtins_root = tmp_path / "builtins"
    (builtins_root / "demo-skill").mkdir(parents=True)
    (builtins_root / "demo-skill" / "SKILL.md").write_text(
        "---\nname: Demo\ndescription: A demo skill.\n---\n\nbody\n"
    )

    registry = BuiltinSkillRegistry.instance()
    registry.register(slug="demo-skill", source_dir=builtins_root / "demo-skill")

    session_dir = tmp_path / "session"
    session_dir.mkdir()

    manifest = materialize_skills(
        session_dir=session_dir,
        user=None,
        db=db_session,
        runtime_builtins_path=builtins_root,
    )

    skill_link = session_dir / ".agents" / "skills" / "demo-skill"
    assert skill_link.is_symlink()
    assert skill_link.resolve() == (builtins_root / "demo-skill").resolve()

    manifest_path = session_dir / ".agents" / "skills" / ".skills_manifest.json"
    assert manifest_path.exists()

    assert len(manifest.builtin) == 1
    assert manifest.builtin[0].slug == "demo-skill"
    assert manifest.builtin[0].source == "builtin"
    assert manifest.custom == []


def test_materialize_skips_templated_builtins(
    tmp_path: Path, db_session: Session
) -> None:
    builtins_root = tmp_path / "builtins"
    (builtins_root / "tpl-skill").mkdir(parents=True)
    (builtins_root / "tpl-skill" / "SKILL.md.template").write_text(
        "---\nname: Tpl\ndescription: Template skill.\n---\n\n{{ ctx.var }}\n"
    )

    registry = BuiltinSkillRegistry.instance()
    registry.register(slug="tpl-skill", source_dir=builtins_root / "tpl-skill")

    session_dir = tmp_path / "session"
    session_dir.mkdir()

    manifest = materialize_skills(
        session_dir=session_dir,
        user=None,
        db=db_session,
        runtime_builtins_path=builtins_root,
    )

    assert manifest.builtin == []
    assert not (session_dir / ".agents" / "skills" / "tpl-skill").exists()
