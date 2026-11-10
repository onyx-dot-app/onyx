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
from onyx.db.resource_version import write_resource_version
from onyx.db.skill import (
    SkillManagementPolicy,
    list_runtime_skills_for_user,
    list_skills,
    resolve_skill_runtime_names,
    set_skill_enabled_for_user,
    skill_user_states,
)
from onyx.db.skill_version import SkillVersionAdapter
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore
from onyx.skills import push
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_built_in_skill_row,
    make_external_app,
    make_group,
    make_skill,
    make_user,
    share_skill_with_group,
    share_skill_with_user,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import client_for

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


@pytest.mark.parametrize("policy", [Policy.DEFAULT, Policy.REQUIRED])
def test_group_duplicates_push_one_complete_bundle(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, policy: Policy
) -> None:
    user = make_user(db_session, standard_account=True)
    group = make_group(db_session)
    add_user_to_group(db_session, user, group)
    first = make_skill(db_session)
    second = make_skill(db_session, name=first.name)
    first.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    second.created_at = first.created_at + timedelta(days=1)
    for skill in (first, second):
        share_skill_with_group(db_session, skill, group).installation_policy = policy
        assert skill.current_version is not None
        skill.current_version.is_valid = True
    db_session.flush()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr(
            "SKILL.md", f"---\nname: {first.name}\ndescription: Test\n---\nWinner"
        )
        bundle.writestr("scripts/run.py", "print('winner')")
    store = MagicMock(spec=FileStore)
    store.read_file.side_effect = lambda *_args, **_kwargs: io.BytesIO(
        output.getvalue()
    )
    monkeypatch.setattr(push, "get_default_file_store", lambda: store)
    monkeypatch.setattr(push, "persist_skill_validity", MagicMock())

    files = push.build_skills_fileset_for_user(user, db_session)
    assert {
        path: content
        for path, content in files.items()
        if path.startswith(first.name + "/")
    } == {
        f"{first.name}/SKILL.md": f"---\nname: {first.name}\ndescription: Test\n---\nWinner".encode(),
        f"{first.name}/scripts/run.py": b"print('winner')",
    }
    assert first.current_version is not None
    store.read_file.assert_called_once()
    assert store.read_file.call_args.args == (first.current_version.bundle_file_id,)
    with client_for(user, db_session) as client:
        response = client.get(f"/skills/{second.id}")
    assert response.status_code == 200, response.text
    assert response.json()["hidden_reason"] == "same_name"
    assert response.json()["hidden_by_skill_id"] == str(first.id)
    assert response.json()["enabled"] is False


@pytest.mark.parametrize(
    "reason", ["off", "invalid", "missing_version", "app", "retired", "not_available"]
)
@pytest.mark.parametrize("include_fallbacks", [False, True])
def test_unusable_company_skill_does_not_hide_own(
    db_session: Session, reason: str, include_fallbacks: bool
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
    runtime = list_runtime_skills_for_user(
        user=user, db_session=db_session, include_fallbacks=include_fallbacks
    )
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


@pytest.mark.parametrize("empty_registry", [False, True])
def test_unknown_builtin_does_not_hide_custom(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, empty_registry: bool
) -> None:
    user = make_user(db_session, standard_account=True)
    stale = make_built_in_skill_row(db_session, built_in_skill_id="removed-builtin")
    own = make_skill(db_session, name=stale.name, author_user_id=user.id)
    own.installation_policy = Policy.DEFAULT
    db_session.flush()
    if empty_registry:
        monkeypatch.setattr("onyx.db.skill.BUILT_IN_SKILLS", {})
    runtime = list_runtime_skills_for_user(user=user, db_session=db_session)
    assert {row.id for row in runtime if row.name == own.name} == {own.id}
    visible = list_skills(
        policy=SkillManagementPolicy.VIEW, user=user, db_session=db_session
    )
    assert own.id in {row.id for row in visible}
    assert stale.id not in {row.id for row in visible}
    state = skill_user_states(user, [own.id], db_session)[own.id]
    assert state.enabled
    assert state.hidden_by_skill_id is None
    with client_for(user, db_session) as client:
        response = client.get(f"/skills/{own.id}")
    assert response.status_code == 200, response.text
    assert response.json()["hidden_by_skill_id"] is None
    assert response.json()["hidden_reason"] is None
    assert response.json()["enabled"] is True


@pytest.mark.parametrize("group_required", [False, True])
def test_own_enabled_skill_precedes_shared_required(
    db_session: Session, group_required: bool
) -> None:
    user = make_user(db_session, standard_account=True)
    other = make_user(db_session, standard_account=True)
    shared = make_skill(db_session, author_user_id=other.id)
    own = make_skill(db_session, name=shared.name, author_user_id=user.id)
    group = make_group(db_session)
    add_user_to_group(db_session, user, group)
    grant = share_skill_with_group(db_session, shared, group)
    if group_required:
        grant.installation_policy = Policy.REQUIRED
    else:
        shared.installation_policy = Policy.REQUIRED
    db_session.flush()
    set_skill_enabled_for_user(
        skill_id=own.id, enabled=True, user=user, db_session=db_session
    )
    states = skill_user_states(user, [own.id, shared.id], db_session)
    assert states[own.id].enabled
    assert not states[shared.id].enabled
    assert states[shared.id].hidden_by_skill_id == own.id
    assert {
        row.id
        for row in list_runtime_skills_for_user(user=user, db_session=db_session)
        if row.name == own.name
    } == {own.id}


def test_company_default_hides_but_preserves_explicit_own_choice(
    db_session: Session,
) -> None:
    user = make_user(db_session, standard_account=True)
    own = make_skill(db_session, author_user_id=user.id)
    company = make_skill(db_session, name=own.name, is_public=True)
    set_skill_enabled_for_user(
        skill_id=own.id, enabled=True, user=user, db_session=db_session
    )
    company.installation_policy = Policy.DEFAULT
    db_session.flush()
    states = skill_user_states(user, [own.id, company.id], db_session)
    assert states[company.id].enabled
    assert states[own.id].hidden_by_skill_id == company.id
    preference = (
        db_session.query(UserSkillPreference)
        .filter_by(user_id=user.id, skill_id=own.id)
        .one()
    )
    assert preference.enabled
    set_skill_enabled_for_user(
        skill_id=company.id, enabled=False, user=user, db_session=db_session
    )
    assert skill_user_states(user, [own.id], db_session)[own.id].enabled
    assert preference.enabled


def _publish(session: Session, skill: Skill, bundle_file_id: str) -> None:
    write_resource_version(
        SkillVersionAdapter(skill),
        bundle_file_id=bundle_file_id,
        bundle_sha256=None,
        is_valid=True,
        metadata=None,
        created_by_user_id=None,
        db_session=session,
    )


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
