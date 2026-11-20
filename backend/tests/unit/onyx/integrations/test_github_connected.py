from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.integrations import github_auth
from onyx.integrations.connections import ResolvedConnection


def test_github_connected_never_refreshes(monkeypatch: pytest.MonkeyPatch) -> None:
    integration, user = MagicMock(), MagicMock()
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        github_auth,
        "_github_integration_and_user",
        lambda _user_id, _db_session: (integration, user),
    )

    def resolve(*_args: Any, **kwargs: Any) -> ResolvedConnection:
        calls.append(kwargs)
        return ResolvedConnection(integration_id=1, connection_id=None, secret=None)

    monkeypatch.setattr(github_auth, "resolve_connection", resolve)

    assert github_auth.github_connected(uuid4(), MagicMock())
    assert calls == [{"refresh": False}]
