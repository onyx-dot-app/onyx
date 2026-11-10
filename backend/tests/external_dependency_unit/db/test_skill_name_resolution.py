import io
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, delete, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.models import Marketplace, Skill, Skill__User, UserSkillPreference
from onyx.db.skill import (
    list_runtime_skills_for_user,
    resolve_skill_runtime_names,
    set_skill_enabled_for_user,
    skill_user_states,
)
from onyx.db.skill_version import repair_skill_version
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore
from onyx.skills import push
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from tests.external_dependency_unit.craft.db_helpers import (
    make_external_app,
    make_skill,
    make_user,
    share_skill_with_user,
)

pytestmark = pytest.mark.usefixtures("tenant_context")


@pytest.mark.parametrize("synced", [False, True])
def test_company_own_shared_priority_and_retirement(
    db_session: Session, synced: bool
) -> None:
    user = make_user(db_session, standard_account=True)
    other = make_user(db_session, standard_account=True)
    shared = make_skill(db_session, author_user_id=other.id)
    own = make_skill(db_session, name=shared.name, author_user_id=user.id)
    company = make_skill(db_session, name=shared.name, is_public=True)
    share_skill_with_user(db_session, shared, user)
    rows = [shared, own, company]
    for index, skill in enumerate(rows):
        skill.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(
            days=index
        )
        skill.installation_policy = Policy.REQUIRED
        if synced:
            source = Marketplace(
                name=f"Source {index}",
                provider=MarketplaceProvider.GITHUB,
                provider_config=GitHubMarketplaceConfig(
                    owner="acme", repo="tools", ref="main"
                ),
                owner_user_id=skill.author_user_id,
            )
            db_session.add(source)
            db_session.flush()
            skill.marketplace_id = source.id
            skill.marketplace_entry_key = skill.name
            # A personal marketplace remains personal when its skill is public.
            own.public_permission = company.public_permission
    db_session.flush()

    for winner, remaining in [
        (company, rows),
        (own, [shared, own]),
        (shared, [shared]),
    ]:
        mapping = resolve_skill_runtime_names(user, db_session)
        assert {row.id: mapping[row.id] for row in remaining} == {
            row.id: winner.id for row in remaining
        }
        runtime = list_runtime_skills_for_user(user=user, db_session=db_session)
        assert {row.id for row in runtime if row.name == company.name} == {winner.id}
        # A detail request must still consider competitors outside the requested set.
        state = skill_user_states(user, [shared.id], db_session)[shared.id]
        assert state.enabled is (winner.id == shared.id)
        assert state.hidden_by_skill_id == (
            None if winner.id == shared.id else winner.id
        )
        winner.retired_at = datetime.now(timezone.utc)
        db_session.flush()
    assert not {row.id for row in rows}.intersection(
        resolve_skill_runtime_names(user, db_session)
    )


@pytest.mark.parametrize(
    "reason", ["off", "invalid", "missing_version", "app", "retired", "not_available"]
)
def test_unusable_company_skill_does_not_hide_own(
    db_session: Session, reason: str
) -> None:
    user = make_user(db_session, standard_account=True)
    company = make_skill(db_session, is_public=True)
    own = make_skill(db_session, name=company.name, author_user_id=user.id)
    company.installation_policy = Policy.DEFAULT
    own.installation_policy = Policy.DEFAULT
    if reason == "off":
        db_session.add(
            UserSkillPreference(
                user_id=user.id, skill_id=company.id, name=company.name, enabled=False
            )
        )
    elif reason == "invalid":
        assert company.current_version is not None
        company.current_version.is_valid = False
    elif reason == "missing_version":
        company.current_version = None
        company.current_version_id = None
    elif reason == "app":
        make_external_app(db_session, skill=company, auth_template={}, enabled=False)
    elif reason == "retired":
        company.retired_at = datetime.now(timezone.utc)
    else:
        company.installation_policy = Policy.NOT_AVAILABLE
    db_session.flush()
    runtime = list_runtime_skills_for_user(user=user, db_session=db_session)
    assert {row.id for row in runtime if row.name == company.name} == {own.id}


def test_required_name_conflict_uses_scope_priority(db_session: Session) -> None:
    user = make_user(db_session, standard_account=True)
    own = make_skill(db_session, author_user_id=user.id)
    company = make_skill(db_session, name=own.name, is_public=True)
    own.installation_policy = Policy.REQUIRED
    db_session.flush()
    set_skill_enabled_for_user(
        skill_id=company.id, enabled=True, user=user, db_session=db_session
    )
    states = skill_user_states(user, [own.id, company.id], db_session)
    assert states[company.id].enabled and not states[own.id].enabled
    own.installation_policy = Policy.AVAILABLE
    company.installation_policy = Policy.REQUIRED
    db_session.flush()
    with pytest.raises(OnyxError) as error:
        set_skill_enabled_for_user(
            skill_id=own.id,
            enabled=True,
            replace_conflict=True,
            user=user,
            db_session=db_session,
        )
    assert error.value.error_code == OnyxErrorCode.SKILL_NAME_CONFLICT


def test_name_index_migration_preserves_rows(isolated_engine: Engine) -> None:
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[3] / "alembic"))
    migration = scripts.get_revision("54013115725e")
    assert migration is not None
    schema = f"name_index_{uuid4().hex}"
    with isolated_engine.connect() as connection, connection.begin():
        connection.execute(text(f"CREATE SCHEMA {schema}"))
        connection.execute(text(f"SET LOCAL search_path TO {schema}"))
        connection.execute(
            text(
                "CREATE TABLE skill (name text, installation_policy text, retired_at timestamptz)"
            )
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.module.downgrade()
            assert "uq_skill_automatic_name" in {
                row["name"] for row in inspect(connection).get_indexes("skill")
            }
            migration.module.upgrade()
            connection.execute(
                text(
                    "INSERT INTO skill VALUES ('same', 'REQUIRED', NULL), ('same', 'DEFAULT', NULL)"
                )
            )
            # Downgrade must refuse a collision instead of changing customer settings.
            with pytest.raises(IntegrityError), connection.begin_nested():
                migration.module.downgrade()
            assert connection.scalar(text("SELECT count(*) FROM skill")) == 2
            connection.execute(
                text(
                    "UPDATE skill SET installation_policy = 'AVAILABLE' WHERE installation_policy = 'DEFAULT'"
                )
            )
            migration.module.downgrade()
            migration.module.upgrade()
            assert inspect(connection).get_indexes("skill") == []


def _publish(session: Session, skill: Skill, bundle_file_id: str) -> None:
    skill.bundle_file_id = bundle_file_id
    skill.is_valid = True
    session.flush()
    repair_skill_version(skill, session)


def test_delivery_reads_the_version_its_access_check_saw(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = make_user(db_session, standard_account=True)
    user = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=owner.id)
    skill.installation_policy = Policy.REQUIRED
    share_skill_with_user(db_session, skill, user)
    bundles: dict[str, bytes] = {}
    for body in ("Shared", "Private"):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("SKILL.md", f"---\nname: {skill.name}\n---\n{body}")
        bundles[f"{body}-{uuid4().hex}"] = output.getvalue()
    shared_bundle, private_bundle = bundles
    _publish(db_session, skill, shared_bundle)
    db_session.commit()
    store = MagicMock(spec=FileStore)
    store.read_file.side_effect = lambda file_id, **_: io.BytesIO(bundles[file_id])
    monkeypatch.setattr(push, "get_default_file_store", lambda: store)
    changes: list[str] = []

    def revoke_and_publish(*args: object) -> None:
        if changes or "first_value" not in str(args[2]):
            return
        changes.append(private_bundle)
        with get_session_with_current_tenant() as owner_session:
            owner_session.execute(
                delete(Skill__User).where(Skill__User.user_id == user.id)
            )
            _publish(
                owner_session, owner_session.get_one(Skill, skill.id), private_bundle
            )
            owner_session.commit()

    with get_session_with_current_tenant() as reader:
        connection = reader.connection()
        event.listen(connection, "after_cursor_execute", revoke_and_publish)
        files = push.build_skills_fileset_for_user(reader.merge(user), reader)
        event.remove(connection, "after_cursor_execute", revoke_and_publish)

    assert changes == [private_bundle]
    assert files[f"{skill.name}/SKILL.md"].endswith(b"Shared")
