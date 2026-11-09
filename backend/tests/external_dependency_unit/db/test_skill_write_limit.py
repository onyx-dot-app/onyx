"""Per-user Skill write limit: set-based usage, recipients and the guard."""

from collections.abc import Generator
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, insert, update
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from onyx.db.enums import AccountType
from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.models import Skill, User, UserSkillPreference
from onyx.db.skill import (
    capture_skill_limit_baseline,
    skill_audience_user_ids,
    skill_limit_violations,
    skill_usage_for_users,
)
from onyx.skills.built_in import get_builtin_skill_footprints
from onyx.skills.limits import (
    SKILL_WRITE_MAX_BYTES,
    SKILL_WRITE_MAX_FILES,
    UNKNOWN_SKILL_BYTES,
    SkillLimit,
    SkillUsage,
)
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_built_in_skill_row,
    make_external_app,
    make_group,
    make_skill,
    make_user,
    make_user_credential,
    share_skill_with_group,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)

pytestmark = pytest.mark.usefixtures("tenant_context")
MIB = 1024 * 1024
NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)


@pytest.fixture
def clean(session: Session) -> Session:
    """Hide Skills from other tests inside this rolled-back transaction."""
    session.execute(update(Skill).values(retired_at=NOW))
    return session


def sized_skill(
    session: Session,
    *,
    size: int | None,
    files: int | None = 1,
    policy: Policy = Policy.DEFAULT,
    author: User | None = None,
    name: str | None = None,
) -> Skill:
    skill = make_skill(
        session,
        name=name,
        is_public=author is None,
        author_user_id=author.id if author is not None else None,
        is_valid=True,
    )
    skill.installation_policy = policy
    version = skill.current_version
    assert version is not None
    version.unpacked_size_bytes = size
    version.file_count = files
    session.flush()
    return skill


def enable(session: Session, user: User, skill: Skill) -> None:
    session.add(
        UserSkillPreference(
            user_id=user.id, skill_id=skill.id, name=skill.name, enabled=True
        )
    )
    session.flush()


def test_usage_counts_runtime_winners_from_metadata(clean: Session) -> None:
    user = make_user(clean, standard_account=True)
    sized_skill(clean, size=10 * MIB, files=3)
    sized_skill(clean, size=50 * MIB, policy=Policy.AVAILABLE)
    chosen = sized_skill(clean, size=7 * MIB, files=2, policy=Policy.AVAILABLE)
    enable(clean, user, chosen)
    # The company skill wins the name over the user's own larger copy.
    shared = sized_skill(clean, size=MIB, name=f"dup-{uuid4().hex[:8]}")
    sized_skill(clean, size=90 * MIB, author=user, name=shared.name)
    sized_skill(clean, size=None, files=None)
    make_built_in_skill_row(clean, built_in_skill_id="github", name="github-limit")

    usage = skill_usage_for_users([user.id], clean)[user.id]

    github = get_builtin_skill_footprints()["github"]
    assert usage == SkillUsage(
        bytes=18 * MIB + github.bytes, files=6 + github.files, unknown_skill_count=1
    )
    assert usage.charged_bytes == usage.bytes + UNKNOWN_SKILL_BYTES
    assert (
        skill_usage_for_users([user.id], clean, exclude_skill_ids=[chosen.id])[
            user.id
        ].bytes
        == usage.bytes - 7 * MIB
    )


def test_app_skill_counts_only_when_the_user_can_use_the_app(clean: Session) -> None:
    ready, no_key, missing = (make_user(clean, standard_account=True) for _ in range(3))
    skill = sized_skill(clean, size=40 * MIB)
    app = make_external_app(
        clean,
        skill=skill,
        auth_template={"Authorization": "Bearer {token}", "X-Team": "{team}"},
    )
    make_user_credential(
        clean, app=app, user=ready, user_credentials={"token": "x", "team": "y"}
    )
    # A credential row without every required key is not a connection.
    make_user_credential(clean, app=app, user=no_key, user_credentials={"token": "x"})

    usage = skill_usage_for_users([ready.id, no_key.id, missing.id], clean)

    assert usage[ready.id].bytes == 40 * MIB
    assert usage[no_key.id] == usage[missing.id] == SkillUsage()
    # A name-limited total reads readiness only for apps of those names.
    assert (
        skill_usage_for_users(
            [ready.id, no_key.id, missing.id], clean, names=[skill.name]
        )
        == usage
    )
    assert skill_usage_for_users([ready.id], clean, names=["other"]) == {
        ready.id: SkillUsage()
    }


def test_audience_includes_users_without_sandboxes(clean: Session) -> None:
    member, outsider = (make_user(clean, standard_account=True) for _ in range(2))
    placeholder = make_user(clean)
    assert placeholder.account_type == AccountType.EXT_PERM_USER
    owner = make_user(clean, standard_account=True)
    group = make_group(clean)
    add_user_to_group(clean, member, group)
    add_user_to_group(clean, placeholder, group)
    skill = sized_skill(clean, size=MIB, author=owner)
    share_skill_with_group(clean, skill, group)

    audience = skill_audience_user_ids([skill.id], clean)

    assert {member.id, owner.id} <= audience
    assert outsider.id not in audience and placeholder.id not in audience


@pytest.mark.parametrize(
    "extra_bytes,extra_files,failed",
    [
        (0, 0, None),
        (1, 0, SkillLimit.BYTES),
        (0, 1, SkillLimit.FILES),
    ],
)
def test_exact_limits(
    clean: Session, extra_bytes: int, extra_files: int, failed: SkillLimit | None
) -> None:
    user = make_user(clean, standard_account=True)
    sized_skill(
        clean,
        size=SKILL_WRITE_MAX_BYTES - 10 * MIB,
        files=SKILL_WRITE_MAX_FILES - 10,
        author=user,
    )
    added = sized_skill(
        clean,
        size=10 * MIB + extra_bytes,
        files=10 + extra_files,
        author=user,
        policy=Policy.AVAILABLE,
    )
    baseline = capture_skill_limit_baseline([added.id], clean, user_ids=[user.id])
    enable(clean, user, added)

    violations = skill_limit_violations(baseline, clean)

    assert {user_id: limit for user_id, (_, limit) in violations.items()} == (
        {user.id: failed} if failed is not None else {}
    )


def test_new_recipient_and_already_over_users(clean: Session) -> None:
    """A user over before a change may shrink; a new recipient may not pass the limit."""
    over, near, low = (make_user(clean, standard_account=True) for _ in range(3))
    big = sized_skill(clean, size=SKILL_WRITE_MAX_BYTES + MIB, author=over)
    sized_skill(clean, size=SKILL_WRITE_MAX_BYTES - MIB, author=near)
    group = make_group(clean)
    for user in (near, low):
        add_user_to_group(clean, user, group)
    added = sized_skill(clean, size=2 * MIB, author=over, policy=Policy.REQUIRED)

    baseline = capture_skill_limit_baseline([added.id], clean)
    share_skill_with_group(clean, added, group)
    violations = skill_limit_violations(baseline, clean)
    assert set(violations) == {near.id}
    assert violations[near.id][1] == SkillLimit.BYTES

    baseline = capture_skill_limit_baseline([big.id], clean)
    version = big.current_version
    assert version is not None
    version.unpacked_size_bytes = SKILL_WRITE_MAX_BYTES
    assert skill_limit_violations(baseline, clean) == {}
    version.unpacked_size_bytes = SKILL_WRITE_MAX_BYTES + 2 * MIB
    assert set(skill_limit_violations(baseline, clean)) == {over.id}


def _insert_users(session: Session, count: int) -> list[UUID]:
    user_ids = [uuid4() for _ in range(count)]
    session.execute(
        insert(User),
        [
            {
                "id": user_id,
                "email": f"limit_{user_id.hex}@example.com",
                "hashed_password": "unused",
                "is_active": True,
                "is_superuser": False,
                "is_verified": True,
                "account_type": AccountType.STANDARD,
            }
            for user_id in user_ids
        ],
    )
    return user_ids


@pytest.fixture
def statements(session: Session) -> Generator[list[str], None, None]:
    executed: list[str] = []
    connection = session.connection()

    def record(_: Connection, __: object, statement: str, *___: object) -> None:
        executed.append(statement)

    event.listen(connection, "before_cursor_execute", record)
    yield executed
    event.remove(connection, "before_cursor_execute", record)


def test_company_change_for_1000_users_uses_constant_queries(
    clean: Session, statements: list[str]
) -> None:
    sized_skill(clean, size=SKILL_WRITE_MAX_BYTES - MIB)
    added = sized_skill(clean, size=2 * MIB, policy=Policy.AVAILABLE)
    counts: list[int] = []
    for count in (10, 990):
        user_ids = _insert_users(clean, count)
        added.installation_policy = Policy.AVAILABLE
        clean.flush()
        statements.clear()
        baseline = capture_skill_limit_baseline([added.id], clean)
        added.installation_policy = Policy.REQUIRED
        violations = skill_limit_violations(baseline, clean)
        counts.append(len(statements))
        assert set(user_ids) <= set(violations)

    assert len(violations) >= 1000
    assert all(limit == SkillLimit.BYTES for _, limit in violations.values())
    assert counts[0] == counts[1] <= 21, counts
