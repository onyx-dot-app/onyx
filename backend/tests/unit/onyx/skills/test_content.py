import io
import zipfile
from pathlib import Path

import pytest

from onyx.skills import built_in as built_in_module
from onyx.skills.built_in import BuiltInSkillDefinition
from onyx.skills.bundle import (
    compute_bundle_manifest,
    custom_bundle_contents_from_stored,
    inspect_custom_bundle,
)
from onyx.skills.content import read_builtin_skill_instructions


def _build_zip(entries: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def built_in_definition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> BuiltInSkillDefinition:
    monkeypatch.setattr(built_in_module, "BUILTIN_SKILLS_PATH", tmp_path)
    skill_id = "preview-test"
    source_dir = tmp_path / skill_id
    source_dir.mkdir()
    return BuiltInSkillDefinition(built_in_skill_id=skill_id)


def test_read_builtin_skill_instructions_strips_frontmatter(
    built_in_definition: BuiltInSkillDefinition,
) -> None:
    (built_in_definition.source_dir / "SKILL.md").write_text(
        "---\nname: Preview\ndescription: Demo\n---\n\n# Instructions\n\nDo it.",
        encoding="utf-8",
    )

    assert (
        read_builtin_skill_instructions(built_in_definition)
        == "# Instructions\n\nDo it."
    )


def test_stored_contents_match_the_bundle() -> None:
    """The editor shows the same instructions and files from the database as
    from the bundle."""
    zip_bytes = _build_zip(
        [
            (
                "SKILL.md",
                b"---\nname: preview\ndescription: Demo\n---\n\n# Instructions\n\nDo it.",
            ),
            ("scripts/run.py", b"print('hi')"),
            ("refs/b.md", b"b"),
        ]
    )
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        skill_md = zf.read("SKILL.md").decode("utf-8")

    from_db = custom_bundle_contents_from_stored(
        skill_md, compute_bundle_manifest(zip_bytes)
    )

    assert from_db == inspect_custom_bundle(zip_bytes)
    assert from_db.instructions_markdown == "# Instructions\n\nDo it."
    assert [entry.path for entry in from_db.files] == ["refs/b.md", "scripts/run.py"]
