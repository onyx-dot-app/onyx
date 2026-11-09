"""A sync blocks only the entry that passes the Skill limit and retries it later."""

import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from queue import Queue
from typing import Any

import pytest
from sqlalchemy import Select, event, func, select, text, true
from sqlalchemy.orm import Session

from onyx.db import marketplace_limits as limit_db
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.enums import SkillInstallationPolicy, SkillSharePermission
from onyx.db.models import Marketplace, Skill, User
from onyx.db.skill import skill_usage_for_users
from onyx.db.skill_version import persist_skill_version_validity
from onyx.skills.limits import SKILL_LIMIT_BLOCK_REASON, SKILL_WRITE_MAX_BYTES
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    marketplace as marketplace,
)
from tests.external_dependency_unit.db.test_marketplace_sync import GitHub, run
from tests.external_dependency_unit.db.test_marketplace_sync import github as github
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    tenant as tenant,
)
from tests.external_dependency_unit.db.test_skill_version_writes import user as user
from tests.external_dependency_unit.db.test_skill_write_limit import sized_skill
from tests.unit.onyx.skills.marketplace_fixtures import CLAUDE, _archive, _catalog, _md

ROOM = 5_000
LARGE = b"x" * 2 * ROOM


def _versions(session: Session) -> dict[str, object]:
    session.expire_all()
    return {
        skill.name: skill.current_version_id
        for skill in session.scalars(
            select(Skill).where(Skill.marketplace_id.is_not(None))
        )
    }


def _catalog_archive(alpha: bytes = b"", beta: bytes = LARGE) -> bytes:
    return _archive(
        {
            CLAUDE: _catalog(skills=["./skills"]),
            "skills/alpha/SKILL.md": _md("alpha") + alpha,
            "skills/beta/SKILL.md": _md("beta") + beta,
        },
        kind="tar",
        wrapper="repo-commit/",
    )


def _key(marketplace: Marketplace, name: str) -> str:
    return next(key for key in marketplace.blocked_entries if key.endswith(name))


def test_sync_blocks_only_the_entry_over_the_limit_and_retries(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    user: User,
) -> None:
    marketplace.public_permission = SkillSharePermission.VIEWER
    marketplace.installation_policy = SkillInstallationPolicy.REQUIRED
    pad = sized_skill(session, size=SKILL_WRITE_MAX_BYTES - ROOM, author=user)
    session.commit()
    github.archive = _catalog_archive()

    result = run(marketplace, tenant)

    assert result.status == "applied"
    assert set(_versions(session)) == {"alpha"}
    session.refresh(marketplace)
    beta = _key(marketplace, "beta")
    assert marketplace.blocked_entries == {beta: SKILL_LIMIT_BLOCK_REASON}
    block = marketplace.skill_limit_blocks.root[beta]
    assert block.affected_user_count == 1 and block.failed_limit == "bytes"
    assert result.skill_limit_blocks[beta] == block

    # The next sync retries the same revision once the user has room.
    version = pad.current_version
    assert version is not None
    version.unpacked_size_bytes = 1
    session.commit()
    result = run(marketplace, tenant)
    assert set(_versions(session)) == {"alpha", "beta"}
    session.refresh(marketplace)
    assert marketplace.blocked_entries == {}
    assert marketplace.skill_limit_blocks.root == {}

    # A larger version is blocked, keeps the current one, and the rest applies.
    before = _versions(session)
    version.unpacked_size_bytes = SKILL_WRITE_MAX_BYTES - 4 * ROOM
    session.commit()
    github.revision = "b" * 40
    github.archive = _catalog_archive(alpha=b"changed", beta=LARGE * 3)
    result = run(marketplace, tenant)
    after = _versions(session)
    assert after["beta"] == before["beta"]
    assert after["alpha"] != before["alpha"]
    session.refresh(marketplace)
    assert marketplace.blocked_entries == {
        _key(marketplace, "beta"): SKILL_LIMIT_BLOCK_REASON
    }


def test_repairing_invalid_version_checks_usage_and_retries(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    user: User,
) -> None:
    marketplace.public_permission = SkillSharePermission.VIEWER
    marketplace.installation_policy = SkillInstallationPolicy.REQUIRED
    session.commit()
    github.archive = _catalog_archive()
    run(marketplace, tenant)
    beta = session.scalar(
        select(Skill).where(
            Skill.marketplace_id == marketplace.id, Skill.name == "beta"
        )
    )
    assert beta is not None and beta.current_version is not None
    old_version_id = beta.current_version_id
    beta.current_version.is_valid = False
    session.flush()
    before = skill_usage_for_users([user.id], session)[user.id]
    pad = sized_skill(
        session, size=SKILL_WRITE_MAX_BYTES - ROOM - before.charged_bytes, author=user
    )
    session.commit()

    github.revision = "c" * 40
    github.archive = _catalog_archive(beta=LARGE[:-1])
    run(marketplace, tenant)

    session.expire_all()
    assert beta.current_version_id == old_version_id
    assert beta.current_version.is_valid is False
    assert marketplace.blocked_entries == {
        _key(marketplace, "beta"): SKILL_LIMIT_BLOCK_REASON
    }
    assert skill_usage_for_users([user.id], session)[user.id].charged_bytes <= (
        SKILL_WRITE_MAX_BYTES
    )

    assert pad.current_version is not None
    pad.current_version.unpacked_size_bytes = 1
    session.commit()
    run(marketplace, tenant)
    session.expire_all()
    assert beta.current_version_id != old_version_id
    assert beta.current_version.is_valid is True
    assert marketplace.blocked_entries == {}


@pytest.mark.parametrize("when", ["before statement", "during statement"])
def test_concurrent_validity_change_is_charged_at_decision_snapshot(
    when: str,
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marketplace.public_permission = SkillSharePermission.VIEWER
    marketplace.installation_policy = SkillInstallationPolicy.REQUIRED
    preferred = sized_skill(session, size=ROOM, name="fallback")
    sized_skill(session, size=5 * ROOM, name="fallback", author=user)
    assert preferred.current_version is not None
    preferred.current_version.is_valid = None
    session.commit()
    github.archive = _catalog_archive()
    run(marketplace, tenant)
    before = skill_usage_for_users([user.id], session)[user.id]
    sized_skill(
        session,
        size=SKILL_WRITE_MAX_BYTES - 3 * ROOM - before.charged_bytes,
        author=user,
    )
    session.commit()
    versions = _versions(session)
    statement = limit_db._decision_statement
    preferred_id = preferred.id
    version_id = preferred.current_version.id
    file_id = preferred.current_version.bundle_file_id
    invalidated: list[str] = []

    def invalidate() -> None:
        with get_session_with_current_tenant() as other:
            persist_skill_version_validity(
                skill_id=preferred_id,
                version_id=version_id,
                bundle_file_id=file_id,
                is_valid=False,
                db_session=other,
            )
            other.commit()
        invalidated.append(when)

    statement_pid: Queue[int] = Queue()

    def identify_statement(_conn: Any, cursor: Any, sql: str, *_args: Any) -> None:
        if "g7i_validity_snapshot" in sql:
            statement_pid.put(cursor.connection.get_backend_pid())

    def during() -> None:
        pid = statement_pid.get(timeout=5)
        with get_session_with_current_tenant() as watcher:
            active = None
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                active = watcher.scalar(
                    text(
                        "SELECT pid FROM pg_stat_activity WHERE state = 'active' "
                        "AND wait_event = 'PgSleep' AND pid = :pid"
                    ),
                    {"pid": pid},
                )
                watcher.rollback()
                if active:
                    break
                time.sleep(0.01)
            assert active, "decision statement never entered its snapshot"
            invalidate()
            assert watcher.scalar(
                text(
                    "SELECT wait_event = 'PgSleep' FROM pg_stat_activity WHERE pid = :pid"
                ),
                {"pid": active},
            ), "mutation must commit during the statement"

    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = []

        def decision(*args: Any, **kwargs: Any) -> Select:
            query = statement(*args, **kwargs).subquery()
            if when == "before statement":
                invalidate()
                return select(*query.c)
            futures.append(executor.submit(copy_context().run, during))
            sleeper = select(func.pg_sleep(2)).subquery()
            return (
                select(*query.c)
                .select_from(query.join(sleeper, true()))
                .prefix_with("/* g7i_validity_snapshot */")
            )

        monkeypatch.setattr(limit_db, "_decision_statement", decision)
        github.revision = "d" * 40
        github.archive = _catalog_archive(alpha=b"x" * ROOM, beta=LARGE + b"x" * ROOM)
        engine = SqlEngine.get_engine()
        event.listen(engine, "before_cursor_execute", identify_statement)
        try:
            run(marketplace, tenant)
        finally:
            event.remove(engine, "before_cursor_execute", identify_statement)
        for future in futures:
            future.result(timeout=5)

    assert invalidated == [when]
    after = _versions(session)
    session.refresh(marketplace)
    if when == "before statement":
        # The larger fallback is already visible: both growth entries must fail.
        assert after == versions
        assert marketplace.blocked_entries == {
            _key(marketplace, "alpha"): SKILL_LIMIT_BLOCK_REASON,
            _key(marketplace, "beta"): SKILL_LIMIT_BLOCK_REASON,
        }
        excess = ROOM
    else:
        # S sees the original validity, exactly as when V commits after sync.
        assert after["alpha"] != versions["alpha"]
        assert after["beta"] != versions["beta"]
        assert marketplace.blocked_entries == {}
        excess = 3 * ROOM
    assert skill_usage_for_users([user.id], session)[user.id].charged_bytes == (
        SKILL_WRITE_MAX_BYTES + excess
    )
