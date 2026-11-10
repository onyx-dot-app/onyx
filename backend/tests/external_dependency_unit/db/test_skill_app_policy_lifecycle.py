import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from queue import Queue

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.external_app import delete_external_app, disconnect_external_app_for_user
from onyx.db.marketplace import reconcile_marketplace__no_commit
from onyx.db.marketplace_access import materialize_marketplace_access__no_commit
from onyx.db.models import ExternalApp, Marketplace, Skill, UserSkillPreference
from onyx.db.skill import list_runtime_skills_for_user
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_external_app,
    make_group,
    make_skill,
    make_user,
    share_skill_with_group,
)
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    catalog,
    stage,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)

pytestmark = pytest.mark.usefixtures("tenant_context", "enable_ee")


def test_app_delete_keeps_retired_policy(session: Session) -> None:
    skill = make_skill(session, is_public=True)
    skill.retired_at = datetime.now(timezone.utc)
    skill.installation_policy = Policy.REQUIRED
    app = make_external_app(session, skill=skill, auth_template={})
    delete_external_app(session, app.id)
    session.refresh(skill)
    assert skill.installation_policy == Policy.REQUIRED


def test_app_delete_waits_before_locking_skills(isolated_engine: Engine) -> None:
    with Session(isolated_engine) as editor:
        skill = make_skill(editor, is_public=True)
        app = make_external_app(editor, skill=skill, auth_template={})
        skill_id, app_id = skill.id, app.id
        editor.commit()
        editor.scalar(
            select(ExternalApp).where(ExternalApp.id == app_id).with_for_update()
        )
        waiting: Queue[int] = Queue()

        def remove() -> None:
            with Session(isolated_engine) as worker:
                worker.execute(text("SET LOCAL statement_timeout = '10s'"))
                pid = worker.scalar(select(func.pg_backend_pid()))
                assert isinstance(pid, int)
                waiting.put(pid)
                delete_external_app(worker, app_id)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(remove)
            try:
                pid = waiting.get(timeout=5)
                with isolated_engine.connect() as observer:
                    deadline = time.monotonic() + 5
                    while not observer.scalar(
                        select(func.cardinality(func.pg_blocking_pids(pid)))
                    ):
                        assert time.monotonic() < deadline
                        time.sleep(0.01)
                # An app editor must still be able to lock its associated skills.
                assert (
                    editor.scalar(
                        select(Skill.id)
                        .where(Skill.id == skill_id)
                        .with_for_update(nowait=True)
                    )
                    == skill_id
                )
            finally:
                editor.rollback()
            future.result(timeout=15)


@pytest.mark.parametrize("action", ["delete", "disconnect"])
@pytest.mark.parametrize("company", [Policy.NOT_AVAILABLE, Policy.REQUIRED])
@pytest.mark.parametrize("group", [None, *Policy])
@pytest.mark.parametrize("enabled", [True, False])
def test_app_lifecycle_preserves_policy_and_user_intent(
    session: Session, action: str, company: Policy, group: Policy | None, enabled: bool
) -> None:
    user = make_user(session, standard_account=True)
    skill = make_skill(session, is_public=True)
    skill.installation_policy = company
    team = make_group(session)
    add_user_to_group(session, user, team)
    share = share_skill_with_group(session, skill, team)
    share.installation_policy = group
    app = make_external_app(session, skill=skill, auth_template={})
    session.add(
        UserSkillPreference(
            user_id=user.id, skill_id=skill.id, name=skill.name, enabled=enabled
        )
    )
    session.flush()
    before = group or company
    if action == "delete":
        delete_external_app(session, app.id)
    else:
        disconnect_external_app_for_user(
            session, external_app_id=app.id, user_id=user.id
        )
    session.expire_all()
    saved = session.get(UserSkillPreference, (user.id, skill.id))
    if not enabled or before == Policy.NOT_AVAILABLE:
        assert saved is not None and saved.enabled == enabled
    else:
        assert saved is None
    automatic = {Policy.DEFAULT, Policy.REQUIRED}
    if action == "delete":
        assert skill.installation_policy == (
            Policy.AVAILABLE if company in automatic else company
        )
        assert share.installation_policy == (
            Policy.AVAILABLE if group in automatic else group
        )
        assert skill.id not in {
            row.id
            for row in list_runtime_skills_for_user(db_session=session, user=user)
        }
    else:
        assert skill.installation_policy == company
        assert share.installation_policy == group


def test_app_deletion_stops_automatic_marketplace_policy_from_returning(
    session: Session,
) -> None:
    source = Marketplace(
        name="App skill source",
        provider=MarketplaceProvider.GITHUB,
        provider_config=GitHubMarketplaceConfig(owner="acme", repo="tools", ref="main"),
        installation_policy=Policy.REQUIRED,
    )
    session.add(source)
    session.flush()
    read = catalog("app-policy")
    reconcile_marketplace__no_commit(
        source.id, read, revision="one", staged=stage(read), db_session=session
    )
    skill = session.scalars(
        select(Skill).where(Skill.marketplace_id == source.id)
    ).one()
    assert (
        skill.installation_policy == Policy.REQUIRED
        and skill.follows_marketplace_access
    )
    app = make_external_app(session, skill=skill, auth_template={})
    delete_external_app(session, app.id)
    materialize_marketplace_access__no_commit(source.id, session)
    assert skill.installation_policy == Policy.AVAILABLE
    assert not skill.follows_marketplace_access
