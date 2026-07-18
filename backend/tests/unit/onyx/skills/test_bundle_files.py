import io
import zipfile

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.skills.bundle import build_single_file_bundle
from onyx.skills.bundle import build_skill_md
from onyx.skills.bundle import inspect_custom_bundle
from onyx.skills.bundle import update_custom_bundle_files


def _zip(entries: list[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, content in entries:
            zf.writestr(path, content)
    return output.getvalue()


def _bundle() -> bytes:
    return build_single_file_bundle(
        "SKILL.md",
        build_skill_md(
            name="demo",
            description="Demo description",
            instructions_markdown="# Instructions\n\nDo the work.",
        ).encode(),
    )


def test_merge_supporting_zip_preserves_skill_md_and_unrelated_files() -> None:
    existing = update_custom_bundle_files(
        _bundle(),
        b"old reference",
        filename="references/context.txt",
    )

    merged = update_custom_bundle_files(
        existing,
        _zip(
            [
                ("references/context.txt", b"new reference"),
                ("scripts/run.py", b"print('hello')\n"),
            ]
        ),
        filename="supporting-files.zip",
    )

    with zipfile.ZipFile(io.BytesIO(merged)) as zf:
        assert zf.read("SKILL.md").endswith(b"Do the work.\n")
        assert zf.read("references/context.txt") == b"new reference"
        assert zf.read("scripts/run.py") == b"print('hello')\n"


def test_skill_bundle_upload_replaces_all_existing_files() -> None:
    existing = update_custom_bundle_files(_bundle(), b"old", filename="old.txt")
    replacement = _zip(
        [
            (
                "replacement/SKILL.md",
                b"---\nname: Replacement\ndescription: New\n---\n\nNew instructions.\n",
            ),
            ("replacement/new.txt", b"new"),
        ]
    )

    updated = update_custom_bundle_files(
        existing,
        replacement,
        filename="replacement.zip",
    )

    with zipfile.ZipFile(io.BytesIO(updated)) as zf:
        assert set(zf.namelist()) == {"SKILL.md", "new.txt"}
        assert zf.read("new.txt") == b"new"


@pytest.mark.parametrize("filename", ["SKILL.md", "skill.md", "Skill.md"])
def test_standalone_skill_md_replaces_existing_bundle(filename: str) -> None:
    existing = update_custom_bundle_files(_bundle(), b"old", filename="old.txt")
    skill_md = b"---\nname: New\ndescription: New desc\n---\n\nNew instructions.\n"

    updated = update_custom_bundle_files(
        existing,
        skill_md,
        filename=filename,
    )

    with zipfile.ZipFile(io.BytesIO(updated)) as zf:
        assert zf.namelist() == ["SKILL.md"]
        assert zf.read("SKILL.md") == skill_md


def test_remove_supporting_file_preserves_skill_md_and_other_files() -> None:
    existing = update_custom_bundle_files(
        _bundle(),
        _zip([("scripts/run.py", b"run"), ("references/context.md", b"context")]),
        filename="files.zip",
    )

    updated = update_custom_bundle_files(
        existing,
        remove_path="scripts/run.py",
    )

    with zipfile.ZipFile(io.BytesIO(updated)) as zf:
        assert set(zf.namelist()) == {"SKILL.md", "references/context.md"}
        assert zf.read("SKILL.md").endswith(b"Do the work.\n")
        assert zf.read("references/context.md") == b"context"


@pytest.mark.parametrize("path", ["SKILL.md", "missing.txt"])
def test_remove_rejects_required_or_missing_file(path: str) -> None:
    expected_message = (
        "SKILL.md cannot be removed" if path == "SKILL.md" else "Skill file not found"
    )

    with pytest.raises(OnyxError, match=expected_message):
        update_custom_bundle_files(_bundle(), remove_path=path)


def test_zip_with_misplaced_skill_md_is_rejected_instead_of_merged() -> None:
    upload = _zip([("outer/inner/SKILL.md", b"invalid")])

    with pytest.raises(OnyxError, match="SKILL.md missing at bundle root"):
        update_custom_bundle_files(_bundle(), upload, filename="nested.zip")


def test_inspect_custom_bundle_returns_instructions_and_sorted_supporting_files() -> (
    None
):
    bundle = update_custom_bundle_files(
        _bundle(),
        _zip([("z.txt", b"zz"), ("docs/a.md", b"a")]),
        filename="files.zip",
    )

    contents = inspect_custom_bundle(bundle)

    assert contents.instructions_markdown == "# Instructions\n\nDo the work."
    assert [file.model_dump() for file in contents.files] == [
        {"path": "docs/a.md", "size": 1},
        {"path": "z.txt", "size": 2},
    ]
