import hashlib
import io
import zipfile
from typing import cast
from unittest.mock import MagicMock

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore
from onyx.skills.ingest import ingest_skill_bundle
from onyx.skills.ingest import ingested_skill_bundle
from onyx.skills.ingest import IngestedBundle


def test_ingest_normalizes_wrapped_bundle_before_hashing_and_storage() -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "example/SKILL.md",
            "---\nname: Example\ndescription: Wrapped skill\n---\n\nInstructions.",
        )
        zf.writestr("example/scripts/helper.py", "print('hello')\n")

    file_store = MagicMock(spec=FileStore)
    file_store.save_file.return_value = "stored-bundle"

    ingested = ingest_skill_bundle(
        source.getvalue(),
        "example.zip",
        file_store,
    )

    saved_stream = file_store.save_file.call_args.kwargs["content"]
    saved_bytes = saved_stream.getvalue()
    with zipfile.ZipFile(io.BytesIO(saved_bytes)) as zf:
        assert set(zf.namelist()) == {"SKILL.md", "scripts/helper.py"}
        assert zf.read("scripts/helper.py") == b"print('hello')\n"

    assert ingested.name == "Example"
    assert ingested.description == "Wrapped skill"
    assert ingested.bundle_file_id == "stored-bundle"
    assert ingested.bundle_sha256 == hashlib.sha256(saved_bytes).hexdigest()
    assert ingested.bundle_sha256 != hashlib.sha256(source.getvalue()).hexdigest()


def test_ingest_standalone_skill_md_uses_frontmatter_name_and_stores_zip() -> None:
    skill_md = (
        b"---\nname: daily-summary\ndescription: Summarizes the day\n---\n\n"
        b"Summarize today's work.\n"
    )
    file_store = MagicMock(spec=FileStore)
    file_store.save_file.return_value = "stored-bundle"

    ingested = ingest_skill_bundle(skill_md, "SKILL.md", file_store)

    assert ingested.slug == "daily-summary"
    assert ingested.name == "daily-summary"
    assert ingested.description == "Summarizes the day"
    saved_stream = file_store.save_file.call_args.kwargs["content"]
    saved_bytes = saved_stream.getvalue()
    with zipfile.ZipFile(io.BytesIO(saved_bytes)) as zf:
        assert zf.namelist() == ["SKILL.md"]
        assert zf.read("SKILL.md") == skill_md
    assert file_store.save_file.call_args.kwargs["display_name"] == (
        "daily-summary.zip"
    )
    assert ingested.bundle_sha256 == hashlib.sha256(saved_bytes).hexdigest()


def test_ingest_standalone_skill_md_requires_slug_compatible_name() -> None:
    skill_md = b"---\nname: Daily Summary\ndescription: Desc\n---\n\nBody\n"
    file_store = MagicMock(spec=FileStore)

    with pytest.raises(OnyxError, match="invalid slug 'Daily Summary'"):
        ingest_skill_bundle(skill_md, "skill.MD", file_store)

    file_store.save_file.assert_not_called()


def test_ingest_standalone_skill_md_replacement_keeps_existing_slug() -> None:
    skill_md = b"---\nname: New Name\ndescription: Desc\n---\n\nBody\n"
    file_store = MagicMock(spec=FileStore)
    file_store.save_file.return_value = "stored-bundle"

    ingested = ingest_skill_bundle(
        skill_md,
        "SKILL.md",
        file_store,
        slug="existing-skill",
    )

    assert ingested.slug == "existing-skill"
    assert ingested.name == "New Name"


def test_ingested_skill_bundle_deletes_new_blob_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_store = cast(FileStore, object())
    delete_bundle_blob = MagicMock()
    monkeypatch.setattr(
        "onyx.skills.ingest.ingest_skill_bundle",
        lambda *_args, **_kwargs: IngestedBundle(
            slug="helper-skill",
            bundle_file_id="new-bundle",
            bundle_sha256="0" * 64,
            name="Helper Skill",
            description="Description",
        ),
    )
    monkeypatch.setattr(
        "onyx.skills.ingest.delete_bundle_blob",
        delete_bundle_blob,
    )

    with pytest.raises(RuntimeError):
        with ingested_skill_bundle(
            b"bundle",
            "helper-skill.zip",
            file_store,
        ):
            raise RuntimeError("db write failed")

    delete_bundle_blob.assert_called_once_with(file_store, "new-bundle")
