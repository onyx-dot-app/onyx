from pathlib import Path

import pytest

from onyx.db.skill import _built_in_skill_folders
from onyx.skills.built_in import BuiltInSkillDefinition
from onyx.skills.content import read_builtin_skill_instructions
from onyx.skills.push import _add_static_builtin


def test_a_built_in_plugin_gives_each_skill_its_own_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = tmp_path / "research"
    for name in ("plan", "report"):
        folder = plugin / "skills" / name
        (folder / "scripts").mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: The {name} step.\n---\nDo the {name}.\n"
        )
        (folder / "scripts" / "run.py").write_text("print('ok')\n")
    (plugin / "README.md").write_text("Not a skill.\n")
    monkeypatch.setattr("onyx.skills.built_in.BUILTIN_SKILLS_PATH", tmp_path)
    definition = BuiltInSkillDefinition(built_in_skill_id="research")

    assert [(s.path, s.name, s.description) for s in definition.skills] == [
        ("skills/plan", "plan", "The plan step."),
        ("skills/report", "report", "The report step."),
    ]
    files: dict[str, bytes] = {}
    _add_static_builtin(files, _built_in_skill_folders(definition), definition)
    assert sorted(files) == [
        "plan/SKILL.md",
        "plan/scripts/run.py",
        "report/SKILL.md",
        "report/scripts/run.py",
    ]
    assert (
        read_builtin_skill_instructions(definition, "skills/report").strip()
        == "Do the report."
    )
