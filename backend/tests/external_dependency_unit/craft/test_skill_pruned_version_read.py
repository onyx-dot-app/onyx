"""Reads of a version whose bundle was pruned."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import PluginVersion, Skill, User
from onyx.db.plugin import BUNDLES_KEPT
from onyx.db.skill import (
    create_custom_skill__no_commit,
    replace_skill_bundle,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.skills.content import (
    VERSION_FILES_NOT_KEPT,
    read_version_bundle_bytes,
    read_version_contents,
)
from onyx.skills.ingest import (
    IngestedBundle,
    delete_bundle_blob,
    ingest_skill_bundle,
)


def _bundle(name: str, version: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle_zip:
        bundle_zip.writestr(
            "SKILL.md",
            f"---\nname: {name}\ndescription: Skill {version}\n---\n\n"
            f"Instructions {version}\n",
        )
    return output.getvalue()


@pytest.fixture
def bundle_ids() -> Iterator[list[str]]:
    ids: list[str] = []
    yield ids
    file_store = get_default_file_store()
    for bundle_file_id in ids:
        delete_bundle_blob(file_store, bundle_file_id)


def _ingest(name: str, version: str, bundle_ids: list[str]) -> IngestedBundle:
    ingested = ingest_skill_bundle(
        _bundle(name, version),
        f"{name}.zip",
        get_default_file_store(),
        expected_name=name,
    )
    bundle_ids.append(ingested.bundle_file_id)
    return ingested


def _create_skill(
    name: str, user: User, bundle_ids: list[str], db_session: Session
) -> Skill:
    skill, _ = create_custom_skill__no_commit(
        _ingest(name, "1", bundle_ids), user, db_session
    )
    db_session.commit()
    return skill


def _version_id(skill_id: UUID, number: int, db_session: Session) -> UUID:
    return db_session.scalars(
        select(PluginVersion.id).where(
            PluginVersion.plugin_id == skill_id,
            PluginVersion.version_number == number,
        )
    ).one()


def _assert_files_not_kept(version_id: UUID, db_session: Session) -> None:
    with pytest.raises(OnyxError) as exc_info:
        read_version_bundle_bytes(version_id, db_session)
    assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND
    assert exc_info.value.detail == VERSION_FILES_NOT_KEPT


def test_read_of_a_pruned_bundle_says_files_are_no_longer_kept(
    db_session: Session,
    test_user: User,
    bundle_ids: list[str],
) -> None:
    name = f"pruned-{test_user.id.hex[:8]}"
    skill = _create_skill(name, test_user, bundle_ids, db_session)
    pruned_file_ids: list[str] = []
    for number in range(2, BUNDLES_KEPT + 2):
        added = replace_skill_bundle(
            skill=skill,
            ingested=_ingest(name, str(number), bundle_ids),
            base_version_id=None,
            user=test_user,
            skip_if_unchanged=False,
            db_session=db_session,
        )
        assert added is not None
        pruned_file_ids.extend(added.pruned_bundle_file_ids)
        db_session.commit()
    assert pruned_file_ids == [bundle_ids[0]]
    for file_id in pruned_file_ids:
        delete_bundle_blob(get_default_file_store(), file_id)

    first_version_id = _version_id(skill.id, 1, db_session)
    _assert_files_not_kept(first_version_id, db_session)
    # The preview of a pruned version reads the content in the database.
    assert (
        "Instructions 1"
        in read_version_contents(first_version_id, db_session).instructions_markdown
    )
