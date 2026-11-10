from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import delete, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema

from onyx.db.enums import SkillSharePermission
from onyx.db.models import (
    Base,
    EncryptedString,
    Marketplace,
    Marketplace__UserGroup,
    Skill,
    SkillVersion,
    User,
)
from onyx.db.skill import set_skill_public_permission
from onyx.db.users import delete_user_from_db__no_commit
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from tests.external_dependency_unit.craft.db_helpers import (
    make_group,
    make_skill,
    make_user,
)

pytestmark = pytest.mark.usefixtures("tenant_context")


@pytest.fixture
def marketplace(db_session: Session) -> Generator[Marketplace, None, None]:
    row = Marketplace(
        name="Company skills",
        provider=MarketplaceProvider.GITHUB,
        provider_config=GitHubMarketplaceConfig(
            owner="acme", repo="skills", ref="main"
        ),
    )
    db_session.add(row)
    db_session.flush()
    try:
        yield row
    finally:
        db_session.rollback()


@pytest.fixture
def migration_session(isolated_engine: Engine) -> Generator[Session, None, None]:
    schema = f"marketplace_migration_{uuid4().hex}"
    tables = {
        Base.metadata.tables[name]
        for name in (
            "marketplace",
            "marketplace__user_group",
            "skill",
            "skill_version",
            "oauth_account",
            "user__pinned_persona",
        )
    }
    while (
        dependencies := {
            fk.column.table for table in tables for fk in table.foreign_keys
        }
        - tables
    ):
        tables |= dependencies
    with isolated_engine.connect() as connection:
        try:
            connection.execute(CreateSchema(schema))
            connection.execute(
                text("SELECT set_config('search_path', :schema, true)"),
                {"schema": schema},
            )
            Base.metadata.create_all(connection, tables=list(tables))
            with Session(connection) as session:
                yield session
        finally:
            connection.rollback()


def test_migration_round_trip_and_refusal(
    migration_session: Session,
) -> None:
    db_session = migration_session
    marketplace = Marketplace(
        name="migration",
        provider=MarketplaceProvider.GITHUB,
        provider_config=GitHubMarketplaceConfig(
            owner="acme", repo="skills", ref="main"
        ),
    )
    db_session.add(marketplace)
    db_session.flush()
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[3] / "alembic"))
    revision = scripts.get_revision("1c894e757414")
    assert revision is not None
    assert revision.down_revision == "13a2d6969b0b"
    skill = make_skill(db_session, is_public=True)
    skill.marketplace_id = marketplace.id
    skill.marketplace_entry_key = "entry/skill"
    db_session.flush()
    connection = db_session.connection()
    with Operations.context(MigrationContext.configure(connection)):
        # Public ownerless marketplace skills must also block the downgrade.
        with pytest.raises(RuntimeError, match="ownerless marketplace skills"):
            revision.module.downgrade()
        skill.public_permission = None
        db_session.flush()
        with pytest.raises(RuntimeError, match="ownerless marketplace skills"):
            revision.module.downgrade()
        skill.author_user_id = make_user(db_session).id
        skill.retired_at = datetime.now(timezone.utc)
        db_session.flush()
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        with pytest.raises(RuntimeError, match="retired skills"):
            revision.module.downgrade()
        skill.retired_at = None
        db_session.flush()
        # Flush deferred version-FK events before ALTER TABLE.
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        revision.module.downgrade()
        assert "marketplace" not in inspect(connection).get_table_names()
        assert (
            connection.scalar(
                text("SELECT name FROM skill WHERE id = :id"), {"id": skill.id}
            )
            == skill.name
        )
        revision.module.upgrade()
        assert "ix_skill_marketplace_id" in {
            index["name"] for index in inspect(connection).get_indexes("skill")
        }
        assert "ix_marketplace__user_group_user_group_id" in {
            index["name"]
            for index in inspect(connection).get_indexes("marketplace__user_group")
        }
        db_session.refresh(skill)
        assert skill.marketplace_id is None
        assert skill.follows_marketplace_access


def test_skill_constraints_and_group_null(
    db_session: Session, marketplace: Marketplace
) -> None:
    skill = make_skill(db_session, is_public=True)
    with pytest.raises(OnyxError, match="Assign an owner"):
        set_skill_public_permission(
            skill=skill, public_permission=None, db_session=db_session
        )
    with pytest.raises(IntegrityError, match="ck_private_skill_has_owner"):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE skill SET public_permission = NULL WHERE id = :id"),
                {"id": skill.id},
            )
    with pytest.raises(IntegrityError, match="ck_skill_marketplace_entry_key"):
        with db_session.begin_nested():
            skill.marketplace_id = marketplace.id
            db_session.flush()
    skill.marketplace_id = marketplace.id
    skill.marketplace_entry_key = "plugin/skill"
    set_skill_public_permission(
        skill=skill, public_permission=None, db_session=db_session
    )
    assert skill.follows_marketplace_access
    with pytest.raises(IntegrityError, match="ck_skill_definition_source"):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE skill SET current_version_id = NULL WHERE id = :id"),
                {"id": skill.id},
            )
    replacement = make_skill(db_session, is_public=True)
    with pytest.raises(IntegrityError, match="uq_skill_live_marketplace_entry"):
        with db_session.begin_nested():
            replacement.marketplace_id = marketplace.id
            replacement.marketplace_entry_key = skill.marketplace_entry_key
            db_session.flush()
    skill.retired_at = datetime.now(timezone.utc)
    db_session.flush()
    replacement.marketplace_id = marketplace.id
    replacement.marketplace_entry_key = skill.marketplace_entry_key
    group = make_group(db_session)
    grant = Marketplace__UserGroup(
        marketplace_id=marketplace.id, user_group_id=group.id
    )
    db_session.add(grant)
    db_session.flush()
    db_session.refresh(grant)
    assert grant.permission == SkillSharePermission.VIEWER
    assert grant.installation_policy is None
    db_session.expire(marketplace)
    assert marketplace.provider_config.ref == "main"
    version = skill.current_version
    assert version is not None
    marketplace_id = marketplace.id
    db_session.execute(delete(Marketplace).where(Marketplace.id == marketplace_id))
    assert db_session.scalar(select(Skill.id).where(Skill.id == skill.id)) is None
    assert (
        db_session.scalar(select(SkillVersion.id).where(SkillVersion.id == version.id))
        is None
    )
    assert (
        db_session.scalar(
            select(Marketplace__UserGroup.marketplace_id).where(
                Marketplace__UserGroup.marketplace_id == marketplace_id
            )
        )
        is None
    )


@pytest.mark.parametrize("raw_delete", [False, True])
def test_personal_owner_cannot_be_deleted(
    db_session: Session, marketplace: Marketplace, raw_delete: bool
) -> None:
    owner = make_user(db_session)
    marketplace.owner_user_id = owner.id
    db_session.flush()
    if raw_delete:
        with pytest.raises(IntegrityError):
            with db_session.begin_nested():
                db_session.execute(delete(User).where(User.__table__.c.id == owner.id))
    else:
        with pytest.raises(OnyxError, match="Company skills"):
            delete_user_from_db__no_commit(owner, db_session)


@pytest.mark.parametrize("raw_delete", [False, True])
@pytest.mark.parametrize("private_synced", [False, True])
def test_login_and_version_creator_deletion(
    db_session: Session,
    marketplace: Marketplace,
    raw_delete: bool,
    private_synced: bool,
) -> None:
    login = make_user(db_session)
    marketplace.login_user_id = login.id
    skill = make_skill(db_session, is_public=True)
    if private_synced:
        skill.marketplace_id = marketplace.id
        skill.marketplace_entry_key = "private/skill"
        skill.author_user_id = login.id
        skill.public_permission = None
    version = skill.current_version
    assert version is not None
    version.created_by_user_id = login.id
    db_session.flush()
    if raw_delete:
        db_session.execute(delete(User).where(User.__table__.c.id == login.id))
    else:
        delete_user_from_db__no_commit(login, db_session)
    db_session.refresh(marketplace)
    db_session.refresh(version)
    assert marketplace.login_user_id is None
    assert version.created_by_user_id is None
    if private_synced:
        db_session.refresh(skill)
        assert skill.author_user_id is None
        assert skill.marketplace_id == marketplace.id
        assert skill.public_permission is None
    if not raw_delete:
        assert (
            marketplace.last_error is not None
            and "Replace the login" in marketplace.last_error
        )


@pytest.mark.usefixtures("enable_ee")
def test_webhook_secret_encryption(
    db_session: Session,
    marketplace: Marketplace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ee.onyx.utils.encryption.ENCRYPTION_KEY_SECRET", uuid4().hex)
    marketplace.webhook_secret = EncryptedString().wrap_raw("test-webhook-value")
    db_session.flush()
    stored = db_session.scalar(
        text("SELECT webhook_secret FROM marketplace WHERE id = :id"),
        {"id": marketplace.id},
    )
    assert stored != b"test-webhook-value"
    db_session.refresh(marketplace)
    assert marketplace.webhook_secret is not None
    assert (
        marketplace.webhook_secret.get_value(apply_mask=False) == "test-webhook-value"
    )
