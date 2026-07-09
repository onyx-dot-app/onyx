from typing import cast
from unittest.mock import MagicMock

import pytest

from onyx.file_store.file_store import FileStore
from onyx.skills.ingest import ingested_skill_bundle
from onyx.skills.ingest import IngestedBundle


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
