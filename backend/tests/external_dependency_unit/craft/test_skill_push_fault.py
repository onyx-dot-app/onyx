"""Skill-push fault-injection: one failing sandbox must not abort pushes to others."""

from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import Skill
from onyx.server.features.build.sandbox.models import FatalWriteError
from onyx.skills.push import push_skills_for_users
from tests.common.craft.stubs import StubSandboxManager
from tests.external_dependency_unit.craft.db_helpers import make_sandbox
from tests.external_dependency_unit.craft.db_helpers import make_user


def test_one_failing_sandbox_does_not_abort_push_to_others(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    seeded_skill: Callable[..., Skill],
    failing_sandbox_manager: Callable[..., StubSandboxManager],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user_a = make_user(db_session)
    user_b = make_user(db_session)
    user_c = make_user(db_session)
    make_sandbox(db_session, user_a, status=SandboxStatus.RUNNING)
    sandbox_b = make_sandbox(db_session, user_b, status=SandboxStatus.RUNNING)
    make_sandbox(db_session, user_c, status=SandboxStatus.RUNNING)
    db_session.commit()

    stub = failing_sandbox_manager(
        fail_on={sandbox_b.id: FatalWriteError("Pod not found")}
    )

    monkeypatch.setattr(
        "onyx.skills.push.get_sandbox_manager",
        lambda: stub,
    )

    seeded_skill(
        slug=f"partial-{uuid4().hex[:6]}",
        public=True,
        bundle_files={"SKILL.md": "p\n"},
    )

    with caplog.at_level(logging.WARNING):
        push_skills_for_users({user_a.id, user_b.id, user_c.id}, db_session)

    assert stub.write_files_to_sandbox_count == 3

    warning_messages = [
        r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert any("1/3 targets failed" in m for m in warning_messages), (
        f"Expected a '1/3 targets failed' partial-failure warning; got: {warning_messages!r}"
    )
