"""The Skill write-limit check equals the full-total rule on mixed random data.

The reference rule measures every affected user's full total before and after
a write. Usage totals also match the single-user runtime resolver.
"""

import random
from collections.abc import Callable, Collection
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from onyx.db import skill as skill_db
from onyx.db.enums import AccountType, SkillSharePermission
from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.external_app import get_ready_external_app_ids_for_users
from onyx.db.models import (
    ExternalAppUserCredential,
    Marketplace,
    Skill,
    Skill__User,
    Skill__UserGroup,
    SkillVersion,
    User,
    UserSkillLimitBlock,
    UserSkillPreference,
)
from onyx.db.skill import (
    _skill_reaches_user,
    available_built_in_skills,
    capture_skill_limit_baseline,
    resolve_skill_runtime_names,
    skill_audience_rows,
    skill_audience_user_ids,
    skill_limit_violations,
    skill_usage_for_users,
    skill_usage_statement,
)
from onyx.skills.built_in import get_builtin_skill_footprints
from onyx.skills.limits import SkillLimit, SkillUsage, failed_skill_limit
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_built_in_skill_row,
    make_external_app,
    make_group,
    make_user,
    make_user_credential,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_write_limit import (
    MIB,
    NOW,
    enable,
    sized_skill,
)
from tests.external_dependency_unit.db.test_skill_write_limit import clean as clean

pytestmark = pytest.mark.usefixtures("tenant_context")
POLICIES = list(Policy)
Violations = dict[UUID, tuple[SkillUsage, SkillLimit]]
# A planned write: the changed Skills, the user for a per-user write, and the change.
Plan = tuple[list[UUID], list[UUID] | None, Callable[[], None]]


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


def _expected(
    before_all: dict[UUID, SkillUsage],
    audience_before: Collection[UUID],
    skill_ids: Collection[UUID],
    user_ids: Collection[UUID] | None,
    session: Session,
) -> Violations:
    """The full-total rule: every affected user's whole usage before and after."""
    session.flush()
    users = (
        set(user_ids)
        if user_ids is not None
        else skill_audience_user_ids(skill_ids, session) | set(audience_before)
    )
    after = skill_usage_for_users(users, session)
    new = users - set(audience_before)
    before = {user: before_all[user] for user in users - new} | skill_usage_for_users(
        new, session, exclude_skill_ids=skill_ids
    )
    expected: Violations = {}
    for user in users:
        failed = failed_skill_limit(after[user], before[user])
        if failed is not None:
            expected[user] = (after[user], failed)
    return expected


class _World:
    def __init__(self, session: Session, seed: int) -> None:
        self.session = session
        self.rng = random.Random(seed)
        rng = self.rng
        self.users = [make_user(session, standard_account=True) for _ in range(14)]
        self.groups = [make_group(session) for _ in range(4)]
        for user in self.users:
            for group in rng.sample(self.groups, rng.randint(0, 2)):
                add_user_to_group(session, user, group)
        names = [f"eq-{seed}-{index}" for index in range(10)]
        self.skills: list[Skill] = []
        for _ in range(22):
            kind = rng.choice(["company", "company", "group", "personal"])
            author = rng.choice(self.users) if kind != "company" else None
            unknown = rng.random() < 0.08
            skill = sized_skill(
                self.session,
                size=None if unknown else rng.randint(1, 160) * MIB,
                files=None if unknown else rng.randint(1, 1500),
                policy=rng.choice(POLICIES),
                author=author,
                name=rng.choice(names) if rng.random() < 0.6 else f"eq-u-{uuid4()}",
            )
            version = skill.current_version
            assert version is not None
            version.is_valid = rng.random() > 0.1
            if kind == "group":
                for group in rng.sample(self.groups, 2):
                    session.add(
                        Skill__UserGroup(
                            skill_id=skill.id,
                            user_group_id=group.id,
                            installation_policy=rng.choice([None, *POLICIES]),
                        )
                    )
            elif kind == "personal" and rng.random() < 0.6:
                for user in rng.sample(self.users, 3):
                    if user.id != skill.author_user_id:
                        session.add(Skill__User(skill_id=skill.id, user_id=user.id))
            self.skills.append(skill)
        session.flush()
        app = make_external_app(
            session,
            skill=self.skills[0],
            auth_template={"Authorization": "Bearer {token}"},
        )
        for user in self.users[:5]:
            make_user_credential(
                session, app=app, user=user, user_credentials={"token": "x"}
            )
        make_built_in_skill_row(
            session, built_in_skill_id="github", name=f"github-{seed}"
        )
        for user in self.users:
            for skill in rng.sample(self.skills, 4):
                self._prefer(user, skill, rng.random() < 0.6)
        for user in rng.sample(self.users, 2):
            session.add(
                UserSkillLimitBlock(
                    user_id=user.id,
                    skill_id=rng.choice(self.skills).id,
                    failed_limit=SkillLimit.BYTES,
                )
            )
        session.flush()

    def _prefer(self, user: User, skill: Skill, enabled: bool) -> None:
        if enabled:
            self.session.execute(
                update(UserSkillPreference)
                .where(
                    UserSkillPreference.user_id == user.id,
                    UserSkillPreference.name == skill.name,
                )
                .values(enabled=False)
            )
        self.session.execute(
            delete(UserSkillPreference).where(
                UserSkillPreference.user_id == user.id,
                UserSkillPreference.skill_id == skill.id,
            )
        )
        self.session.add(
            UserSkillPreference(
                user_id=user.id, skill_id=skill.id, name=skill.name, enabled=enabled
            )
        )
        self.session.flush()

    def plans(self) -> list[Callable[[], Plan]]:
        rng, session = self.rng, self.session

        def resize() -> Plan:
            skill = rng.choice(self.skills)
            unknown = rng.random() < 0.15
            size = None if unknown else rng.randint(0, 300) * MIB
            files = None if unknown else rng.randint(0, 3000)
            # Repairing an invalid version can grow usage from zero.
            valid = rng.random() < 0.9

            def apply() -> None:
                version = skill.current_version
                assert version is not None
                version.unpacked_size_bytes = size
                version.file_count = files
                version.is_valid = valid

            return [skill.id], None, apply

        def toggle() -> Plan:
            user, skill = rng.choice(self.users), rng.choice(self.skills)
            enabled = rng.random() < 0.5
            return [skill.id], [user.id], lambda: self._prefer(user, skill, enabled)

        def access() -> Plan:
            skill = rng.choice(self.skills)
            change = rng.randrange(4)
            policy = rng.choice(POLICIES)
            group = rng.choice(self.groups)
            owner = rng.choice(self.users)

            def apply() -> None:
                if change == 0 and skill.public_permission is None:
                    skill.public_permission = SkillSharePermission.VIEWER
                elif change == 0:
                    skill.public_permission = None
                    skill.author_user_id = skill.author_user_id or owner.id
                elif change == 1:
                    skill.installation_policy = policy
                elif change == 2:
                    session.execute(
                        delete(Skill__UserGroup).where(
                            Skill__UserGroup.skill_id == skill.id
                        )
                    )
                    session.add(
                        Skill__UserGroup(
                            skill_id=skill.id,
                            user_group_id=group.id,
                            installation_policy=policy,
                        )
                    )
                else:
                    skill.author_user_id = owner.id

            return [skill.id], None, apply

        def unblock() -> Plan:
            block = session.scalars(select(UserSkillLimitBlock)).first()
            if block is None:
                return resize()
            return [block.skill_id], [block.user_id], lambda: session.delete(block)

        return [resize, resize, toggle, access, access, unblock]


@pytest.mark.parametrize("seed", range(6))
def test_check_matches_full_total_rule(clean: Session, seed: int) -> None:
    world = _World(clean, seed)
    outcomes = {"violations": 0, "clean": 0}
    for _ in range(14):
        skill_ids, write_users, apply = world.rng.choice(world.plans())()
        savepoint = clean.begin_nested()
        baseline = capture_skill_limit_baseline(skill_ids, clean, user_ids=write_users)
        before_all = skill_usage_for_users(baseline.before.keys(), clean)
        apply()
        actual = skill_limit_violations(baseline, clean)
        assert actual == _expected(
            before_all, baseline.before.keys(), skill_ids, write_users, clean
        )
        outcomes["violations" if actual else "clean"] += 1
        clean.expire_all()
        everyone = skill_usage_for_users([user.id for user in world.users], clean)
        for user in world.users:
            expected = _runtime_usage(user, clean)
            assert skill_usage_for_users([user.id], clean)[user.id] == expected
            assert everyone[user.id] == expected, user.id
        savepoint.rollback()
    assert outcomes["violations"] and outcomes["clean"], outcomes


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
    users = [make_user(session, standard_account=True) for _ in range(9)]
    plain, preferring, shared, grouped, blocked, credentialed = users[:6]
    author, owner, stranger = users[6:]
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
    session.add(
        UserSkillLimitBlock(
            user_id=blocked.id, skill_id=common.id, failed_limit=SkillLimit.BYTES
        )
    )
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
        blocked.id: -8,
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


@pytest.mark.parametrize("seed", range(6))
def test_staged_version_usage_matches_published_pointers(
    session: Session, seed: int
) -> None:
    """Overrides and compressed name rows equal real pointer changes in both shapes."""
    world = _World(session, seed)
    users = [user.id for user in world.users]
    audience = set(
        session.execute(
            skill_audience_rows([skill.id for skill in world.skills])
        ).tuples()
    )
    audience_users = session.scalars(
        select(User.__table__.c.id).where(
            User.__table__.c.is_active.is_(True),
            User.account_type.not_in([AccountType.BOT, AccountType.EXT_PERM_USER]),
        )
    )
    expected_audience = {
        (skill_id, user_id)
        for user_id in audience_users
        for skill_id in session.scalars(
            select(Skill.id).where(
                Skill.id.in_([skill.id for skill in world.skills]),
                _skill_reaches_user(user_id),
            )
        )
    }
    assert audience == expected_audience
    generic = uuid4()
    ready = get_ready_external_app_ids_for_users(session, [*users, generic])
    available = available_built_in_skills(session)
    overrides: dict[UUID, UUID | None] = {}
    originals: dict[UUID, UUID | None] = {}
    for index, skill in enumerate(world.skills[:6]):
        originals[skill.id] = skill.current_version_id
        version = SkillVersion(
            id=uuid4(),
            skill_id=skill.id,
            version_number=2,
            bundle_file_id=f"staged-{uuid4()}",
            bundle_sha256="0" * 64,
            is_valid=index % 3 != 0,
            unpacked_size_bytes=index * MIB,
            file_count=index + 1,
        )
        session.add(version)
        overrides[skill.id] = version.id
    # A staged new custom row must have a pointer, but was absent before sync.
    absent = sized_skill(session, size=10 * MIB, files=5, name="staged-new")
    overrides[absent.id] = None
    session.flush()
    totals = {
        user: SkillUsage(int(size), int(files), int(unknown))
        for user, _, size, files, unknown, _ in session.execute(
            skill_usage_statement(
                users,
                ready,
                generic,
                built_in_available=available,
                version_overrides=overrides,
            )
        )
    }
    names = {skill.name for skill in world.skills} | {absent.name}
    by_name = {
        (user, name): SkillUsage(int(size), int(files), int(unknown))
        for user, name, size, files, unknown, _ in session.execute(
            skill_usage_statement(
                users,
                ready,
                generic,
                built_in_available=available,
                version_overrides=overrides,
                names=names,
                per_name=True,
            )
        )
    }
    for skill in world.skills[:6]:
        skill.current_version_id = overrides[skill.id]
    session.flush()
    assert totals == skill_usage_for_users(
        users, session, exclude_skill_ids=[absent.id]
    )
    for name in names:
        expected = skill_usage_for_users(
            users, session, names=[name], exclude_skill_ids=[absent.id]
        )
        assert {
            user: by_name.get((user, name), by_name.get((generic, name), SkillUsage()))
            for user in users
        } == expected
