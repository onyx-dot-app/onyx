"""An OAuth callback reloads the Craft session of the user and commits the
skill push state."""

from collections.abc import Callable
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from starlette.requests import Request

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import BuildSessionStatus, SandboxStatus
from onyx.db.models import BuildSession, Sandbox, Skill
from onyx.integrations.connection_models import IntegrationOAuthCallbackResult
from onyx.server.features.integrations import connections_api
from onyx.server.features.integrations.models import IntegrationOAuthCallbackRequest
from tests.common.craft.stubs import StubSandboxManager
from tests.external_dependency_unit.craft.db_helpers import make_sandbox, make_user


def test_oauth_callback_commits_the_skill_push_of_the_user(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    seeded_skill: Callable[..., Skill],
    failing_sandbox_manager: Callable[..., StubSandboxManager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user, status=SandboxStatus.RUNNING)
    db_session.add(
        BuildSession(
            user_id=user.id,
            status=BuildSessionStatus.ACTIVE,
            opencode_session_id=f"opencode-{uuid4()}",
        )
    )
    db_session.commit()
    seeded_skill(
        name=f"reload-{uuid4().hex[:6]}",
        public=True,
        bundle_files={"SKILL.md": "r\n"},
    )
    stub = failing_sandbox_manager(fail_on={})
    monkeypatch.setattr("onyx.skills.push.get_sandbox_manager", lambda: stub)
    result = IntegrationOAuthCallbackResult(
        integration_id=1, for_organization=False, return_path=None
    )

    with patch.object(
        connections_api, "complete_integration_oauth", return_value=result
    ):
        connections_api.oauth_callback(
            Request({"type": "http"}),
            IntegrationOAuthCallbackRequest(code="code", state="state"),
            user,
            db_session,
        )

    with get_session_with_current_tenant() as fresh:
        stored = fresh.get(Sandbox, sandbox.id)
        assert stored is not None and stored.skills_hash is not None
