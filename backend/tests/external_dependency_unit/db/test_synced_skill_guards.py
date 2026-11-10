"""Synced content is source-owned; retirement hides reads and releases names."""

from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.enums import SkillSharePermission as Share
from onyx.db.external_app import (
    associate_custom_skill_with_external_app__no_commit,
    get_skill_external_app_dependencies,
    get_skills_for_external_app,
    replace_custom_skill_associations__no_commit,
)
from onyx.db.models import (
    ExternalApp__Skill,
    Marketplace,
    Skill,
    User,
    UserSkillPreference,
)
from onyx.db.skill import (
    SkillManagementPolicy,
    SkillUserState,
    affected_user_ids_for_skill,
    list_runtime_skills_for_user,
    list_skills,
    set_skill_enabled_for_user,
    set_skill_installation_policy,
    skill_user_states,
    transfer_skill_ownership,
)
from onyx.db.skill_version import save_skill_version
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.external_apps.api import _to_admin_response
from onyx.server.features.skill import api, response_helpers
from tests.external_dependency_unit.craft.db_helpers import (
    make_external_app,
    make_sandbox,
    make_skill,
    make_user,
)
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    apply,
    catalog,
    skills,
    stage,
)
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    marketplace as marketplace,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    client_for,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)

pytestmark = pytest.mark.usefixtures("tenant_context", "enable_ee")


@pytest.mark.parametrize("personal", [False, True])
@pytest.mark.parametrize("retired", [False, True])
@pytest.mark.parametrize(
    "operation",
    ["patch", "bundle", "upload", "remove", "restore", "transfer", "delete"],
)
def test_source_owned_mutations(
    session: Session,
    marketplace: Marketplace,
    personal: bool,
    retired: bool,
    operation: str,
) -> None:
    actor = make_user(session, standard_account=True, is_admin=not personal)
    if personal:
        marketplace.owner_user_id = actor.id
    apply(session, marketplace, catalog("guarded"))
    skill = skills(session, marketplace)[0]
    if retired:
        skill.retired_at = datetime.now(timezone.utc)
    session.commit()
    path = f"/skills/custom/{skill.id}"
    with (
        client_for(actor, session) as client,
        patch.object(api, "get_default_file_store") as storage,
    ):
        if operation == "patch":
            response = client.patch(path, json={"description": "Changed"})
        elif operation == "bundle":
            response = client.put(
                f"{path}/bundle", files={"bundle": ("a.zip", b"invalid")}
            )
        elif operation == "upload":
            response = client.post(
                f"{path}/files", files={"upload": ("note.txt", b"a")}
            )
        elif operation == "remove":
            response = client.delete(f"{path}/files", params={"path": "note.txt"})
        elif operation == "restore":
            response = client.post(
                f"{path}/versions/{skill.current_version_id}/restore"
            )
        elif operation == "transfer":
            response = client.post(
                f"{path}/transfer-ownership", json={"new_owner_user_id": str(actor.id)}
            )
        else:
            with patch.object(api, "delete_unreferenced_skill_bundles"):
                response = client.delete(path)
        if retired and operation == "delete":
            assert response.status_code == 200, response.text
            assert session.get(Skill, skill.id) is None
        else:
            assert response.status_code == 400, response.text
            assert ("retired" if retired else "GitHub") in response.json()["detail"]
        storage.assert_not_called()


@pytest.mark.parametrize("personal", [False, True])
def test_live_synced_access_and_toggle_remain_editable(
    session: Session, marketplace: Marketplace, personal: bool
) -> None:
    actor = make_user(session, standard_account=True, is_admin=not personal)
    recipient = make_user(session, standard_account=True)
    if personal:
        marketplace.owner_user_id = actor.id
    else:
        marketplace.public_permission = Share.VIEWER
    apply(session, marketplace, catalog("shared"))
    skill = skills(session, marketplace)[0]
    session.commit()
    with client_for(actor, session) as client:
        result = client.patch(
            f"/skills/custom/{skill.id}/share",
            json={
                "user_shares": [{"user_id": str(recipient.id), "permission": "VIEWER"}]
            },
        )
        assert result.status_code == 200, result.text
        assert (
            client.put(
                f"/skills/{skill.id}/enabled", json={"enabled": True}
            ).status_code
            == 200
        )
        skill.installation_policy = Policy.REQUIRED
        session.commit()
        assert (
            client.put(
                f"/skills/{skill.id}/enabled", json={"enabled": False}
            ).status_code
            == 400
        )
        skill.retired_at = datetime.now(timezone.utc)
        session.commit()
        for response in [
            client.put(f"/skills/{skill.id}/enabled", json={"enabled": False}),
            client.patch(f"/skills/custom/{skill.id}/share", json={"user_shares": []}),
            client.patch(f"/skills/custom/{skill.id}", json={}),
        ]:
            assert (
                response.status_code == 400
                and response.json()["detail"]
                == "This skill is retired and cannot be changed."
            )


def test_retired_reads_hidden_and_bulk_delete_allowed(
    session: Session, marketplace: Marketplace
) -> None:
    admin = make_user(session, is_admin=True)
    owner = make_user(session, standard_account=True)
    marketplace.owner_user_id = owner.id
    make_sandbox(session, owner)
    apply(session, marketplace, catalog("old", "live"))
    old, live = sorted(
        skills(session, marketplace), key=lambda row: row.name, reverse=True
    )
    app = make_external_app(session, skill=old, auth_template={})
    session.add(ExternalApp__Skill(external_app_id=app.id, skill_id=live.id))
    old.retired_at = datetime.now(timezone.utc)
    old.installation_policy = Policy.REQUIRED
    session.add(
        UserSkillPreference(
            user_id=owner.id, skill_id=old.id, name=old.name, enabled=True
        )
    )
    session.commit()
    assert owner.id in affected_user_ids_for_skill(old, session)
    assert old.current_version is not None
    assert [row.id for row in get_skills_for_external_app(session, app.id)] == [live.id]
    assert old.id not in get_skill_external_app_dependencies(session, owner)
    assert [
        row.id
        for row in _to_admin_response(
            app, stored={}, db_session=session
        ).associated_skills
    ] == [live.id]
    for actor in (owner, admin):
        for policy in (SkillManagementPolicy.VIEW, SkillManagementPolicy.EDIT):
            assert old.id not in {
                row.id
                for row in list_skills(policy=policy, user=actor, db_session=session)
            }
        assert old.id not in skill_user_states(actor, [old.id], session)
        assert old.id not in {
            row.id
            for row in list_runtime_skills_for_user(user=actor, db_session=session)
        }
        with client_for(actor, session) as client:
            for path in [
                f"/{old.id}",
                f"/{old.id}/preview",
                f"/custom/{old.id}/edit",
                f"/custom/{old.id}/share",
            ]:
                assert client.get(f"/skills{path}").status_code == 404, path
            # The personal owner and global managers keep read-only history.
            history = client.get(f"/skills/custom/{old.id}/versions")
            assert history.status_code == 200, history.text
            assert [row["id"] for row in history.json()] == [
                str(old.current_version_id)
            ]
    with (
        client_for(owner, session) as client,
        patch.object(api, "delete_unreferenced_skill_bundles"),
    ):
        result = client.post(
            "/skills/bulk",
            json={"action": "delete", "skill_ids": [str(old.id), str(live.id)]},
        )
    assert result.status_code == 200, result.text
    assert result.json()["succeeded"] == [str(old.id)]
    assert result.json()["failed"][0]["skill_id"] == str(live.id)
    assert "GitHub" in result.json()["failed"][0]["detail"]


def test_retirement_releases_preference_and_automatic_names(
    session: Session, marketplace: Marketplace
) -> None:
    owner = make_user(session, standard_account=True)
    marketplace.owner_user_id = owner.id
    apply(session, marketplace, catalog("reused"))
    old = skills(session, marketplace)[0]
    set_skill_enabled_for_user(
        skill_id=old.id, enabled=True, user=owner, db_session=session
    )
    set_skill_installation_policy(old, Policy.DEFAULT, session)
    session.commit()
    version_id = old.current_version_id
    apply(session, marketplace, catalog())
    session.expire_all()
    assert old.retired_at is not None and old.current_version_id == version_id
    preference = session.get(UserSkillPreference, (owner.id, old.id))
    assert preference is not None and not preference.enabled
    apply(session, marketplace, catalog("reused"))
    new = session.scalar(
        select(Skill).where(
            Skill.marketplace_id == marketplace.id, Skill.retired_at.is_(None)
        )
    )
    assert new is not None and new.id != old.id
    set_skill_installation_policy(new, Policy.DEFAULT, session)
    set_skill_enabled_for_user(
        skill_id=new.id, enabled=True, user=owner, db_session=session
    )
    session.commit()
    assert {
        row.id
        for row in list_runtime_skills_for_user(user=owner, db_session=session)
        if row.is_custom
    } == {new.id}
    with pytest.raises(OnyxError, match="GitHub"):
        transfer_skill_ownership(
            skill=new, new_owner_user_id=owner.id, db_session=session
        )
    ingested = next(iter(stage(catalog("reused")).values()))
    with pytest.raises(OnyxError, match="GitHub"):
        save_skill_version(new, ingested, owner.id, session)


def test_retirement_migration_preserves_reused_live_policy(session: Session) -> None:
    owner = make_user(session, standard_account=True)
    old = make_skill(session, name="migration-reused", author_user_id=owner.id)
    old.retired_at = datetime.now(timezone.utc)
    old.installation_policy = Policy.REQUIRED
    new = make_skill(session, name=old.name, author_user_id=owner.id)
    new.installation_policy = Policy.DEFAULT
    session.add(
        UserSkillPreference(
            user_id=owner.id, skill_id=old.id, name=old.name, enabled=True
        )
    )
    session.flush()
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[3] / "alembic"))
    revision = scripts.get_revision("99814f2364b2")
    # 54013115725e later drops the index that 99814f2364b2 replaces.
    name_index_removal = scripts.get_revision("54013115725e")
    assert revision is not None and name_index_removal is not None
    # Fixture inserts leave deferred checks that block index creation.
    session.execute(text("SET CONSTRAINTS fk_skill_current_version IMMEDIATE"))
    with Operations.context(MigrationContext.configure(session.connection())):
        name_index_removal.module.downgrade()
        revision.module.downgrade()
        revision.module.upgrade()
        name_index_removal.module.upgrade()
    session.expire_all()
    assert new.installation_policy == Policy.DEFAULT
    assert old.installation_policy == Policy.AVAILABLE
    preference = session.get(UserSkillPreference, (owner.id, old.id))
    assert preference is not None and not preference.enabled


@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("linked", [False, True])
def test_app_association_refreshes_retirement(
    session: Session, bulk: bool, linked: bool
) -> None:
    owner = make_user(session, standard_account=True)
    seed = make_skill(session, author_user_id=owner.id)
    app = make_external_app(session, skill=seed, auth_template={})
    target = make_skill(session, author_user_id=owner.id)
    if linked:
        session.add(ExternalApp__Skill(external_app_id=app.id, skill_id=target.id))
        session.flush()
    session.execute(
        update(Skill)
        .where(Skill.id == target.id)
        .values(retired_at=datetime.now(timezone.utc)),
        execution_options={"synchronize_session": False},
    )
    assert target.retired_at is None
    if bulk and linked:
        replace_custom_skill_associations__no_commit(
            session, external_app_id=app.id, skill_ids=[target.id]
        )
    else:
        with pytest.raises(OnyxError, match="retired"):
            if bulk:
                replace_custom_skill_associations__no_commit(
                    session, external_app_id=app.id, skill_ids=[target.id]
                )
            else:
                associate_custom_skill_with_external_app__no_commit(
                    session, external_app_id=app.id, skill_id=target.id
                )
    assert (session.get(ExternalApp__Skill, (app.id, target.id)) is not None) == linked


@pytest.mark.parametrize("include_retired", [False, True])
def test_app_replacement_preserves_retired_association(
    session: Session, include_retired: bool
) -> None:
    owner = make_user(session, standard_account=True)
    target = make_skill(session, author_user_id=owner.id)
    app = make_external_app(session, skill=target, auth_template={})
    session.execute(
        update(Skill)
        .where(Skill.id == target.id)
        .values(retired_at=datetime.now(timezone.utc)),
        execution_options={"synchronize_session": False},
    )
    assert target.retired_at is None
    replacement = make_skill(session, name=target.name, author_user_id=owner.id)
    permission = target.public_permission
    affected = replace_custom_skill_associations__no_commit(
        session,
        external_app_id=app.id,
        skill_ids=[replacement.id, *([target.id] if include_retired else [])],
    )
    assert session.get(ExternalApp__Skill, (app.id, target.id)) is not None
    assert target.public_permission == permission
    assert [skill.id for skill in affected] == [replacement.id]
    assert [skill.id for skill in get_skills_for_external_app(session, app.id)] == [
        replacement.id
    ]


@pytest.mark.parametrize("single", [False, True])
def test_retirement_between_load_and_response(session: Session, single: bool) -> None:
    owner = make_user(session, standard_account=True)
    skill = make_skill(session, author_user_id=owner.id)
    unaffected = make_skill(session, author_user_id=owner.id)
    read_states = response_helpers.skill_user_states

    def retire_then_read(
        user: User, skill_ids: Iterable[UUID], db_session: Session
    ) -> dict[UUID, SkillUserState]:
        session.execute(
            update(Skill)
            .where(Skill.id == skill.id)
            .values(retired_at=datetime.now(timezone.utc)),
            execution_options={"synchronize_session": False},
        )
        return read_states(user, skill_ids, db_session)

    with (
        client_for(owner, session) as client,
        patch.object(
            response_helpers, "skill_user_states", side_effect=retire_then_read
        ),
    ):
        response = client.get(f"/skills/{skill.id}" if single else "/skills")
    assert response.status_code == (404 if single else 200), response.text
    if not single:
        ids = {row["id"] for row in response.json()["customs"]}
        assert str(skill.id) not in ids
        assert str(unaffected.id) in ids
