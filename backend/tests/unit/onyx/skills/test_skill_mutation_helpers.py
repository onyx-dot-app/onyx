import io
from unittest.mock import MagicMock

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.mutation_helpers import ingested_skill_bundle
from onyx.server.features.skill.mutation_helpers import reject_reserved_skill_slug
from onyx.skills.ingest import IngestedBundle


def test_reject_reserved_skill_slug_blocks_built_in_slug() -> None:
    with pytest.raises(OnyxError) as exc_info:
        reject_reserved_skill_slug("pptx.zip")

    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_ingested_skill_bundle_deletes_new_blob_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_store = object()
    delete_bundle_blob = MagicMock()
    monkeypatch.setattr(
        "onyx.server.features.skill.mutation_helpers.get_default_file_store",
        lambda: file_store,
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.mutation_helpers.read_bundle_file",
        lambda bundle_file: bundle_file.read(),
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.mutation_helpers.ingest_skill_bundle",
        lambda *_args, **_kwargs: IngestedBundle(
            slug="helper-skill",
            bundle_file_id="new-bundle",
            bundle_sha256="0" * 64,
            name="Helper Skill",
            description="Description",
        ),
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.mutation_helpers.delete_bundle_blob",
        delete_bundle_blob,
    )

    with pytest.raises(RuntimeError):
        with ingested_skill_bundle(
            bundle_file=io.BytesIO(b"bundle"),
            filename="helper-skill.zip",
        ):
            raise RuntimeError("db write failed")

    delete_bundle_blob.assert_called_once_with(file_store, "new-bundle")
