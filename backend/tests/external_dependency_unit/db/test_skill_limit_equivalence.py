"""Skill usage totals match the single-user runtime resolver in both query shapes."""

from collections.abc import Collection
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.db import skill as skill_db
from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.models import (
    ExternalAppUserCredential,
    Marketplace,
    Skill,
    Skill__User,
    Skill__UserGroup,
    User,
)
from onyx.db.skill import (
    resolve_skill_runtime_names,
    skill_usage_for_users,
)
from onyx.skills.built_in import get_builtin_skill_footprints
from onyx.skills.limits import SkillUsage
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_external_app,
    make_group,
    make_user,
    make_user_credential,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_write_limit import (
    NOW,
    enable,
    sized_skill,
)
from tests.external_dependency_unit.db.test_skill_write_limit import clean as clean

pytestmark = pytest.mark.usefixtures("tenant_context")


@pytest.fixture(autouse=True, params=["shared winners", "per-user winners"])
def winner_query(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run every case through both usage query shapes."""
    limit = 0 if request.param == "shared winners" else 1_000_000
    monkeypatch.setattr(skill_db, "PER_USER_WINNER_MAX_NAME_PAIRS", limit)
    monkeypatch.setattr(skill_db, "PER_USER_WINNER_MAX_FULL_TOTAL_USERS", limit)


def _runtime_usage(user: User, session: Session) -> SkillUsage:
    winners = set(resolve_skill_runtime_names(user, session).values())
    total = SkillUsage()
    for skill in session.scalars(select(Skill).where(Skill.id.in_(winners))):
        if skill.built_in_skill_id is not None:
            footprint = get_builtin_skill_footprints().get(skill.built_in_skill_id)
            if footprint is not None:
                total += SkillUsage(bytes=footprint.bytes, files=footprint.files)
            continue
        version = skill.current_version
        assert version is not None
        if version.unpacked_size_bytes is None or version.file_count is None:
            total += SkillUsage(unknown_skill_count=1)
        else:
            total += SkillUsage(
                bytes=version.unpacked_size_bytes, files=version.file_count
            )
    return total


def _marketplace(session: Session, owner: User) -> Marketplace:
    marketplace = Marketplace(
        name=f"Personal {uuid4().hex[:8]}",
        provider=MarketplaceProvider.GITHUB,
        provider_config=GitHubMarketplaceConfig(owner="a", repo="b", ref="main"),
        owner_user_id=owner.id,
    )
    session.add(marketplace)
    session.flush()
    return marketplace


def test_each_user_row_kind_replaces_the_generic_winner(clean: Session) -> None:
    """Each kind of per-user row changes one user's winner for one name.

    Every user's total must still equal the single-user runtime resolver.
    """
    session = clean
    users = [make_user(session, standard_account=True) for _ in range(8)]
    plain, preferring, shared, grouped, credentialed = users[:5]
    author, owner, stranger = users[5:]
    # Available needs an explicit enable.
    enable(session, preferring, sized_skill(session, size=1, policy=Policy.AVAILABLE))
    personal = sized_skill(session, size=2, author=author)
    session.add(Skill__User(skill_id=personal.id, user_id=shared.id))
    group = make_group(session)
    add_user_to_group(session, grouped, group)
    session.add(
        Skill__UserGroup(
            skill_id=sized_skill(session, size=4, author=author).id,
            user_group_id=group.id,
        )
    )
    common = sized_skill(session, size=8)
    app = make_external_app(
        session,
        skill=sized_skill(session, size=16),
        auth_template={"Authorization": "Bearer {token}"},
    )
    make_user_credential(
        session, app=app, user=credentialed, user_credentials={"token": "x"}
    )
    # The organization fills the credential, so every user can use this app.
    make_external_app(
        session,
        skill=sized_skill(session, size=128),
        auth_template={"Authorization": "Bearer {token}"},
        organization_credentials={"token": "x"},
    )
    # The older Skill wins unless the user owns the other library.
    name = f"library-{uuid4().hex[:8]}"
    for size, library_owner in ((32, stranger), (64, owner)):
        skill = sized_skill(session, size=size, name=name)
        skill.author_user_id = None
        skill.marketplace_id = _marketplace(session, library_owner).id
        skill.marketplace_entry_key = f"skills/{name}"
        skill.created_at = NOW + timedelta(minutes=size)
    session.flush()
    session.expire_all()

    usage = skill_usage_for_users([user.id for user in users], session)

    for user in users:
        assert usage[user.id] == _runtime_usage(user, session), user.id
    generic = usage[plain.id].bytes
    assert {user.id: usage[user.id].bytes - generic for user in users} == {
        plain.id: 0,
        preferring.id: 1,
        shared.id: 2,
        grouped.id: 4,
        credentialed.id: 16,
        author.id: 2 + 4,
        owner.id: 64 - 32,
        stranger.id: 0,
    }
    ids = [plain.id, owner.id, author.id]
    assert {
        user_id: usage.bytes
        for user_id, usage in skill_usage_for_users(ids, session, names=[name]).items()
    } == {plain.id: 32, owner.id: 64, author.id: 32}
    without = skill_usage_for_users(ids, session, exclude_skill_ids=[common.id])
    assert without[plain.id].bytes == generic - 8


def test_usage_keeps_the_readiness_input_after_credentials_change(
    clean: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_user(clean, standard_account=True)
    app = make_external_app(
        clean,
        skill=sized_skill(clean, size=123),
        auth_template={"Authorization": "Bearer {token}"},
    )
    make_user_credential(clean, app=app, user=user, user_credentials={"token": "x"})
    read_ready = skill_db.get_ready_external_app_ids_for_users

    def disconnect_after_read(
        session: Session,
        user_ids: Collection[UUID],
        *,
        skill_names: Collection[str] | None = None,
    ) -> dict[UUID, set[int]]:
        ready = read_ready(session, user_ids, skill_names=skill_names)
        session.execute(
            delete(ExternalAppUserCredential).where(
                ExternalAppUserCredential.user_id == user.id,
                ExternalAppUserCredential.external_app_id == app.id,
            )
        )
        return ready

    with monkeypatch.context() as patch:
        patch.setattr(
            skill_db, "get_ready_external_app_ids_for_users", disconnect_after_read
        )
        assert skill_usage_for_users([user.id], clean) == {
            user.id: SkillUsage(bytes=123, files=1)
        }
    assert skill_usage_for_users([user.id], clean) == {user.id: SkillUsage()}


def test_missing_users_have_no_skill_usage(clean: Session) -> None:
    user = make_user(clean, standard_account=True)
    missing = uuid4()
    sized_skill(clean, size=123)
    assert skill_usage_for_users([user.id, missing], clean) == {
        user.id: SkillUsage(bytes=123, files=1),
        missing: SkillUsage(),
    }
