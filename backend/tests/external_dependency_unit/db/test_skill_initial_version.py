"""Custom creation works with a non-null, deferred version pointer."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from onyx.db.marketplace import reconcile_marketplace__no_commit
from onyx.db.models import Marketplace, Skill, SkillVersion, User
from onyx.db.resource_version import write_resource_version
from onyx.db.skill import create_skill_from_ingested_bundle
from onyx.db.skill_version import SkillVersionAdapter
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from tests.external_dependency_unit.craft.db_helpers import make_skill
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    catalog,
    stage,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    tenant as tenant,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    user as user,
)


@pytest.mark.parametrize("source", ["upload", "personal", "company", "fixture"])
def test_creation_with_required_version_pointer(
    session: Session, user: User, source: str, tenant: str
) -> None:
    # This tenant schema belongs to the test; the V7 check is immediate.
    schema = session.connection().dialect.identifier_preparer.quote_schema(tenant)
    session.execute(
        text(
            f"ALTER TABLE {schema}.skill ADD CONSTRAINT ck_test_skill_version "
            "CHECK ((built_in_skill_id IS NULL) <> (current_version_id IS NULL))"
        )
    )
    read = catalog("versioned")
    bundles = stage(read)
    ingested = next(iter(bundles.values()))
    if source == "upload":
        skill = create_skill_from_ingested_bundle(ingested, user.id, session)
    elif source == "fixture":
        skill = make_skill(
            session,
            name=ingested.canonical_name,
            author_user_id=user.id,
            bundle_file_id=ingested.bundle_file_id,
            bundle_sha256=ingested.bundle_sha256,
        )
    else:
        marketplace = Marketplace(
            name="Versioned source",
            provider=MarketplaceProvider.GITHUB,
            provider_config=GitHubMarketplaceConfig(
                owner="acme", repo="tools", ref="main"
            ),
            owner_user_id=user.id if source == "personal" else None,
        )
        session.add(marketplace)
        session.flush()
        reconcile_marketplace__no_commit(
            marketplace.id,
            read,
            revision="initial",
            staged=bundles,
            db_session=session,
        )
        skill = session.scalars(select(Skill)).one()
    session.commit()
    first = skill.current_version
    assert first is not None
    assert first.id == skill.current_version_id
    assert first.skill_id == skill.id
    assert first.version_number == 1
    assert first.bundle_file_id == ingested.bundle_file_id

    # A fresh writer allocates a new ID instead of reusing the reserved first ID.
    second = write_resource_version(
        SkillVersionAdapter(skill),
        bundle_file_id="second-bundle",
        bundle_sha256="a" * 64,
        is_valid=True,
        metadata=ingested.metadata,
        created_by_user_id=user.id,
        db_session=session,
    )
    session.commit()
    assert second.id != first.id
    assert second.version_number == 2
    assert skill.current_version_id == second.id
    assert session.scalars(
        select(SkillVersion).order_by(SkillVersion.version_number)
    ).all() == [first, second]
