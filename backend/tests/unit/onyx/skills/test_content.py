import io
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from onyx.db.models import Skill, SkillVersion
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore, read_file_to_buffer
from onyx.skills import built_in as built_in_module
from onyx.skills.built_in import BuiltInSkillDefinition
from onyx.skills.bundle import STORED_BUNDLE_LIMITS
from onyx.skills.content import (
    read_builtin_skill_instructions,
    read_custom_skill_bundle_bytes,
    read_custom_skill_bundle_instructions,
)


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
        Skill(
            name="preview-test",
            current_version=SkillVersion(bundle_file_id="bundle-file-id"),
        ),
        file_store,
    )

    file_store.read_file.assert_called_once_with(
        "bundle-file-id", max_bytes=STORED_BUNDLE_LIMITS.max_stored_bytes
    )
    assert instructions == "# Instructions\n\nDo it."


def test_missing_current_version_is_an_internal_error() -> None:
    with pytest.raises(OnyxError) as error:
        read_custom_skill_bundle_bytes(Skill(name="broken"), Mock(spec=FileStore))
    assert error.value.error_code == OnyxErrorCode.INTERNAL_ERROR


@pytest.mark.parametrize(
    "failure", [TimeoutError("storage timeout"), OSError("storage unavailable")]
)
def test_current_bundle_storage_errors_keep_structured_response(
    failure: Exception,
) -> None:
    store = Mock(spec=FileStore)
    store.read_file.side_effect = failure
    with pytest.raises(OnyxError) as error:
        read_custom_skill_bundle_bytes(
            Skill(
                name="preview-test",
                current_version=SkillVersion(bundle_file_id="bundle"),
            ),
            store,
        )
    assert error.value.error_code == OnyxErrorCode.INTERNAL_ERROR
    assert error.value.detail == "Failed to read bundle for skill 'preview-test'."
    assert error.value.__cause__ is failure


def test_missing_current_bundle_is_internal_error() -> None:
    store = Mock(spec=FileStore)
    store.read_file.side_effect = FileNotFoundError("missing")
    with pytest.raises(OnyxError) as error:
        read_custom_skill_bundle_bytes(
            Skill(
                name="preview-test",
                current_version=SkillVersion(bundle_file_id="bundle"),
            ),
            store,
        )
    assert error.value.error_code == OnyxErrorCode.INTERNAL_ERROR


def test_current_bundle_over_read_limit_has_specific_payload_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.file_store.models import BundleLimits
    from onyx.skills import content

    monkeypatch.setattr(
        content,
        "STORED_BUNDLE_LIMITS",
        BundleLimits(max_stored_bytes=8, max_file_bytes=8, max_total_bytes=8),
    )
    source = io.BytesIO(b"x" * 9)

    def bounded_read(file_id: str, *, max_bytes: int) -> io.BytesIO:
        assert file_id == "bundle"
        read_file_to_buffer(source.read, use_tempfile=False, max_bytes=max_bytes)
        pytest.fail("The oversized stored file must be refused")

    store = Mock(spec=FileStore)
    store.read_file.side_effect = bounded_read
    with pytest.raises(OnyxError) as error:
        read_custom_skill_bundle_bytes(
            Skill(
                name="preview-test",
                current_version=SkillVersion(bundle_file_id="bundle"),
            ),
            store,
        )
    assert error.value.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE
    assert (
        error.value.detail
        == "Stored bundle for skill 'preview-test' exceeds the 8-byte read limit."
    )
    assert source.tell() == 9


def test_current_bundle_over_expansion_limit_has_payload_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.file_store.models import BundleLimits
    from onyx.skills import content

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("SKILL.md", b"x" * 9)
    monkeypatch.setattr(
        content,
        "STORED_BUNDLE_LIMITS",
        BundleLimits(max_stored_bytes=10_000, max_file_bytes=8, max_total_bytes=8),
    )
    store = Mock(spec=FileStore)
    store.read_file.return_value = io.BytesIO(output.getvalue())
    with pytest.raises(OnyxError) as error:
        read_custom_skill_bundle_bytes(
            Skill(
                name="preview-test",
                current_version=SkillVersion(bundle_file_id="bundle"),
            ),
            store,
        )
    assert error.value.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE
