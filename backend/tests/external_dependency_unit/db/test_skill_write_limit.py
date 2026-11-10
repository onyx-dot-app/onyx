"""Per-user Skill write limit: set-based usage."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.models import Skill, User, UserSkillPreference
from onyx.db.skill import skill_usage_for_users
from onyx.skills.built_in import get_builtin_skill_footprints
from onyx.skills.limits import UNKNOWN_SKILL_BYTES, SkillUsage
from tests.external_dependency_unit.craft.db_helpers import (
    make_built_in_skill_row,
    make_external_app,
    make_skill,
    make_user,
    make_user_credential,
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
