from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType, SkillSharePermission
from onyx.db.external_app import associate_built_in_skill__no_commit
from onyx.db.marketplace import reconcile_marketplace__no_commit
from onyx.db.models import (
    ExternalApp,
    Marketplace,
    Skill,
    SkillVersion,
    User,
    User__UserGroup,
)
from onyx.db.skill import (
    SkillSharingChange,
    create_skill_from_bundle__no_commit,
    create_skill_from_ingested_bundle,
)
from onyx.db.skill_version import save_skill_version
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.models import BundleMetadata
from onyx.skills.ingest import IngestedBundle
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from tests.external_dependency_unit.craft.db_helpers import make_skill, make_user
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    catalog,
    stage,
)

pytestmark = pytest.mark.usefixtures("tenant_context", "enable_ee")


@pytest.mark.parametrize("app_type", [ExternalAppType.LINEAR, ExternalAppType.ZENDESK])
def test_builtin_setup_preserves_older_custom_name(
    db_session: Session, app_type: ExternalAppType
) -> None:
    name = app_type.value.lower()
    legacy = make_skill(db_session, name=name, is_public=True)
    app = ExternalApp(name=name, app_type=app_type, enabled=True)
    db_session.add(app)
    db_session.flush()
    builtin = associate_built_in_skill__no_commit(db_session, app)
    db_session.flush()
    assert builtin.id != legacy.id and builtin.name == legacy.name
    assert builtin.built_in_skill_id == name
    assert legacy.built_in_skill_id is None
    assert builtin in app.associated_skills


def bundle(name: str) -> IngestedBundle:
    return IngestedBundle(
        canonical_name=name,
        description="Library write test",
        bundle_file_id=str(uuid4()),
        bundle_sha256="0" * 64,
        metadata=BundleMetadata(
            content_digest="0" * 64, unpacked_size_bytes=10, file_count=1
        ),
    )


def test_final_library_and_historical_duplicates(db_session: Session) -> None:
    owner = make_user(db_session, is_admin=True)
    name = f"g3-{uuid4().hex}"
    personal = create_skill_from_ingested_bundle(bundle(name), owner.id, db_session)
    company, _, _ = create_skill_from_bundle__no_commit(
        bundle(name),
        SkillSharingChange(
            public_permission=SkillSharePermission.VIEWER, set_public_permission=True
        ),
        False,
        owner,
        db_session,
    )
    assert personal.public_permission is None
    assert company.public_permission == SkillSharePermission.VIEWER
    with pytest.raises(OnyxError) as caught, db_session.begin_nested():
        create_skill_from_bundle__no_commit(
            bundle(name),
            SkillSharingChange(
                public_permission=SkillSharePermission.VIEWER,
                set_public_permission=True,
            ),
            False,
            owner,
            db_session,
        )
    assert caught.value.error_code == OnyxErrorCode.SKILL_NAME_CONFLICT
    # Low-level fixtures can still represent duplicates that predate enforcement.
    old = make_skill(db_session, name=name, author_user_id=owner.id)
    assert old.id != personal.id
    personal.retired_at = old.retired_at = datetime.now(timezone.utc)
    db_session.flush()
    replacement = create_skill_from_ingested_bundle(bundle(name), owner.id, db_session)
    assert replacement.id != personal.id


@pytest.mark.parametrize("same_library", [True, False])
@pytest.mark.parametrize("second_is_sync", [True, False])
def test_concurrent_creation(
    db_session: Session, same_library: bool, second_is_sync: bool
) -> None:
    engine = db_session.get_bind()
    assert isinstance(engine, Engine)
    owners = [make_user(db_session, is_admin=True) for _ in range(2)]
    owner_ids = [owner.id for owner in owners]
    name = f"g3-{uuid4().hex}"
    source = Marketplace(
        name=name,
        provider=MarketplaceProvider.GITHUB,
        provider_config=GitHubMarketplaceConfig(owner="acme", repo="tools", ref="main"),
        owner_user_id=None if same_library else owners[1].id,
    )
    db_session.add(source)
    db_session.commit()
    source_id = source.id
    db_session.rollback()
    barrier = Barrier(2)

    def create(index: int) -> str:
        with Session(engine) as session:
            barrier.wait(timeout=10)
            if index == 1 and second_is_sync:
                read = catalog(name)
                result = reconcile_marketplace__no_commit(
                    source_id,
                    read,
                    revision="first",
                    staged=stage(read),
                    db_session=session,
                )
                session.commit()
                return "conflict" if result.blocked_entries else "created"
            try:
                skill = create_skill_from_ingested_bundle(
                    bundle(name),
                    owner_ids[index],
                    session,
                    intended_public_permission=SkillSharePermission.VIEWER
                    if same_library
                    else None,
                )
                if same_library:
                    skill.public_permission = SkillSharePermission.VIEWER
                session.commit()
                return "created"
            except OnyxError as exc:
                assert exc.error_code == OnyxErrorCode.SKILL_NAME_CONFLICT
                session.rollback()
                return "conflict"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, range(2)))
        assert sorted(results) == (
            ["conflict", "created"] if same_library else ["created", "created"]
        )
        assert db_session.scalar(
            select(func.count()).select_from(Skill).where(Skill.name == name)
        ) == (1 if same_library else 2)
    finally:
        for skill in db_session.scalars(select(Skill).where(Skill.name == name)):
            db_session.delete(skill)
        db_session.flush()
        db_session.execute(delete(Marketplace).where(Marketplace.id == source_id))
        db_session.execute(
            delete(User__UserGroup).where(User__UserGroup.user_id.in_(owner_ids))
        )
        db_session.execute(delete(User).where(User.__table__.c.id.in_(owner_ids)))
        db_session.commit()


def test_direct_version_writer_rejects_renaming(db_session: Session) -> None:
    user = make_user(db_session, standard_account=True)
    ingested = bundle(f"g3-{uuid4().hex}")
    skill = create_skill_from_ingested_bundle(ingested, user.id, db_session)
    version_id = skill.current_version_id
    with (
        pytest.raises(OnyxError, match="name cannot change"),
        db_session.begin_nested(),
    ):
        save_skill_version(
            skill,
            ingested._replace(canonical_name="different-name"),
            user.id,
            db_session,
            initial=True,
        )
    assert skill.current_version_id == version_id
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(SkillVersion)
            .where(SkillVersion.skill_id == skill.id)
        )
        == 1
    )
