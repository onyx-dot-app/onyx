from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from onyx.db.persona import update_personas_display_priority


def _persona(persona_id: int, display_priority: int) -> SimpleNamespace:
    return SimpleNamespace(id=persona_id, display_priority=display_priority)


def test_update_display_priority_updates_subset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persona_a = _persona(1, 5)
    persona_b = _persona(2, 6)
    db_session = MagicMock()
    user = MagicMock()
    monkeypatch.setattr(
        "onyx.db.persona.get_raw_personas_for_user",
        lambda user, db_session, **kwargs: [persona_a, persona_b],
    )

    update_personas_display_priority(
        {persona_a.id: 0}, db_session, user, commit_db_txn=True
    )

    assert persona_a.display_priority == 0
    assert persona_b.display_priority == 6
    db_session.commit.assert_called_once_with()


def test_update_display_priority_invalid_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    persona_a = _persona(1, 5)
    db_session = MagicMock()
    user = MagicMock()
    monkeypatch.setattr(
        "onyx.db.persona.get_raw_personas_for_user",
        lambda user, db_session, **kwargs: [persona_a],
    )

    with pytest.raises(ValueError):
        update_personas_display_priority(
            {persona_a.id: 0, 99: 1}, db_session, user, commit_db_txn=True
        )

    db_session.commit.assert_not_called()
