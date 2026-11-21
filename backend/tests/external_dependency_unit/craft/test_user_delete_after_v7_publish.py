"""A user delete works after the user's skill was published by code that no
longer writes the old skill rows. The old row stays private with the user as
author, so the delete sets its author to NULL."""

import io
import zipfile
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from onyx.db.enums import MarketplaceKind, SkillSharePermission
from onyx.db.models import Marketplace, Plugin, User
from onyx.db.skill import create_custom_skill__no_commit, set_skill_public_permission
from onyx.db.users import delete_user_from_db__no_commit
from onyx.file_store.file_store import get_default_file_store
from onyx.skills.ingest import delete_bundle_blob, ingest_skill_bundle
from tests.external_dependency_unit.craft.db_helpers import make_user

_old_skill_table = sa.table(
    "skill",
    sa.column("id", sa.Uuid),
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
    sa.column("built_in_skill_id", sa.String),
    sa.column("bundle_file_id", sa.String),
    sa.column("public_permission", sa.String),
    sa.column("author_user_id", sa.Uuid),
)


@pytest.fixture
def bundle_ids() -> Iterator[list[str]]:
    ids: list[str] = []
    yield ids
    file_store = get_default_file_store()
    for bundle_file_id in ids:
        delete_bundle_blob(file_store, bundle_file_id)


def _bundle(name: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle_zip:
        bundle_zip.writestr(
            "SKILL.md", f"---\nname: {name}\ndescription: Old skill\n---\n\nBody\n"
        )
    return output.getvalue()


def test_user_delete_after_publish_keeps_the_published_skill(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    bundle_ids: list[str],
) -> None:
    author = make_user(db_session, standard_account=True)
    name = f"old-row-{author.id.hex[:8]}"
    ingested = ingest_skill_bundle(
        _bundle(name), f"{name}.zip", get_default_file_store(), expected_name=name
    )
    bundle_ids.append(ingested.bundle_file_id)
    skill, _ = create_custom_skill__no_commit(ingested, author, db_session)
    db_session.execute(
        sa.insert(_old_skill_table).values(
            id=skill.id,
            name=name,
            description="Old skill",
            built_in_skill_id=None,
            bundle_file_id=ingested.bundle_file_id,
            public_permission=None,
            author_user_id=author.id,
        )
    )
    set_skill_public_permission(
        skill=skill,
        public_permission=SkillSharePermission.VIEWER,
        db_session=db_session,
    )
    db_session.commit()

    deleted = db_session.get(User, author.id)
    assert deleted is not None
    delete_user_from_db__no_commit(deleted, db_session)
    db_session.commit()

    plugin = db_session.get(Plugin, skill.id, populate_existing=True)
    assert plugin is not None
    assert plugin.author_user_id is None
    assert plugin.published_version_id == plugin.current_version_id
    assert (
        db_session.scalar(
            sa.select(Marketplace.kind).where(Marketplace.id == plugin.marketplace_id)
        )
        == MarketplaceKind.ORGANIZATION_LIBRARY
    )
