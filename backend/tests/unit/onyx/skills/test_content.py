import io
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from onyx.db.models import Skill
from onyx.file_store.file_store import FileStore
from onyx.skills import built_in as built_in_module
from onyx.skills.built_in import BuiltInSkillDefinition
from onyx.skills.content import read_builtin_skill_instructions
from onyx.skills.content import read_custom_skill_bundle_instructions


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


def test_read_custom_skill_bundle_instructions_reads_bundle_from_file_store() -> None:
    zip_bytes = _build_zip(
        [
            (
                "SKILL.md",
                b"---\nname: Preview\ndescription: Demo\n---\n\n# Instructions\n\nDo it.",
            ),
            ("scripts/run.py", b"print('hi')"),
        ]
    )
    file_store = Mock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(zip_bytes)

    instructions = read_custom_skill_bundle_instructions(
        Skill(slug="preview-test", bundle_file_id="bundle-file-id"),
        file_store,
    )

    file_store.read_file.assert_called_once_with("bundle-file-id")
    assert instructions == "# Instructions\n\nDo it."
