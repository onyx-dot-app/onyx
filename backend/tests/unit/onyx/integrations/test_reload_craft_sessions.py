from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.integrations.service import reload_craft_sessions
from onyx.server.features.build.session import sandbox_lifecycle
from onyx.skills import push


def test_reload_commits_the_skill_push_state(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = MagicMock()
    monkeypatch.setattr(
        sandbox_lifecycle, "refresh_mcp_config_hashes_for_users", MagicMock()
    )
    monkeypatch.setattr(push, "push_skills_for_users", calls.push)
    db_session = MagicMock(spec=Session)
    db_session.commit = calls.commit

    reload_craft_sessions({uuid4()}, db_session)

    assert [call[0] for call in calls.mock_calls] == ["push", "commit"]
