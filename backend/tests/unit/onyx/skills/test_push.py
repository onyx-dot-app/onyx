from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

from onyx.db.models import Skill
from onyx.file_store.file_store import FileStore
from onyx.server.features.build.sandbox.models import FileSet
from onyx.skills.metadata import parse_skill_md_frontmatter
from onyx.skills.push import _add_from_bundle


def test_add_from_bundle_normalizes_legacy_name_without_mutating_metadata() -> None:
    legacy_skill_md = (
        b"---\n"
        b"name: Legacy Display Name\n"
        b"description: Legacy description\n"
        b"license: Apache-2.0\n"
        b"allowed-tools: Read\n"
        b"x-custom:\n"
        b"  retained: true\n"
        b"---\n\n# Instructions\n\nDo the work.\n"
    )
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as bundle_zip:
        bundle_zip.writestr("SKILL.md", legacy_skill_md)
        bundle_zip.writestr("scripts/run.py", b"print('hello')\n")

    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(bundle.getvalue())
    skill = cast(
        Skill,
        SimpleNamespace(slug="canonical-name", bundle_file_id="bundle-id"),
    )
    files: FileSet = {}

    _add_from_bundle(files, skill, file_store)

    frontmatter, instructions = parse_skill_md_frontmatter(
        files["canonical-name/SKILL.md"]
    )
    assert frontmatter == {
        "name": "canonical-name",
        "description": "Legacy description",
        "license": "Apache-2.0",
        "allowed-tools": "Read",
        "x-custom": {"retained": True},
    }
    assert instructions.strip() == "# Instructions\n\nDo the work."
    assert files["canonical-name/scripts/run.py"] == b"print('hello')\n"

    with zipfile.ZipFile(io.BytesIO(bundle.getvalue())) as stored_bundle:
        assert stored_bundle.read("SKILL.md") == legacy_skill_md
