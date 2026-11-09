"""Visible skills expose source labels without granting marketplace management."""

import re

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from onyx.db.enums import SkillSharePermission
from onyx.db.models import Marketplace
from tests.external_dependency_unit.craft.db_helpers import make_skill, make_user
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    apply,
    catalog,
    skills,
)
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    marketplace as marketplace,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    client_for,
    manager,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)

pytestmark = pytest.mark.usefixtures("tenant_context", "enable_ee")


@pytest.mark.parametrize("personal", [False, True])
def test_source_labels_on_list_and_detail(
    session: Session, marketplace: Marketplace, personal: bool
) -> None:
    reader = make_user(session, standard_account=True)
    if personal:
        marketplace.owner_user_id = reader.id
    else:
        marketplace.public_permission = SkillSharePermission.VIEWER
    apply(session, marketplace, catalog("first", "second"))
    imported = skills(session, marketplace)
    uploaded = make_skill(session, author_user_id=reader.id)
    session.commit()
    queries: list[str] = []

    def capture(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if re.search(r"\bFROM\s+(?:\w+\.)?marketplace\b", statement):
            queries.append(statement)

    with client_for(reader, session) as client:
        connection = session.connection()
        event.listen(connection, "before_cursor_execute", capture)
        try:
            response = client.get("/skills")
        finally:
            event.remove(connection, "before_cursor_execute", capture)
        assert response.status_code == 200, response.text
        assert len(queries) == 1
        assert "webhook_secret" not in queries[0]
        assert "provider_config" not in queries[0]
        assert "login_user_id" not in queries[0]
        rows = {row["id"]: row for row in response.json()["customs"]}
        assert rows[str(uploaded.id)]["marketplace"] is None
        for skill in imported:
            expected = {
                "id": str(marketplace.id),
                "name": marketplace.name,
                "personal": personal,
                "folder": f"skills/{skill.name}",
                "follows_access": skill.follows_marketplace_access,
            }
            assert rows[str(skill.id)]["marketplace"] == expected
            detail = client.get(f"/skills/{skill.id}")
            assert detail.status_code == 200, detail.text
            assert detail.json()["marketplace"] == expected
            assert detail.json()["retired_at"] is None


def test_source_tracks_move_and_access_override(
    session: Session, marketplace: Marketplace
) -> None:
    admin, _ = manager(session, global_access=True)
    marketplace.public_permission = SkillSharePermission.VIEWER
    apply(session, marketplace, catalog("movable"))
    skill = skills(session, marketplace)[0]
    session.commit()
    with client_for(admin, session) as client:
        changed = client.patch(
            f"/skills/custom/{skill.id}/share",
            json={"public_permission": "EDITOR"},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["marketplace"]["follows_access"] is False
        reset = client.post(f"/skills/custom/{skill.id}/reset-marketplace-access")
        assert reset.status_code == 200, reset.text
        assert reset.json()["marketplace"]["follows_access"] is True
        apply(session, marketplace, catalog("movable", folder="moved"), revision="two")
        marketplace.name = "Renamed source"
        session.commit()
        moved = client.get(f"/skills/{skill.id}")
        assert moved.status_code == 200, moved.text
        assert moved.json()["marketplace"]["name"] == "Renamed source"
        assert moved.json()["marketplace"]["folder"] == "moved/movable"


def test_hidden_skills_do_not_disclose_sources(
    session: Session, marketplace: Marketplace
) -> None:
    owner = make_user(session, standard_account=True)
    outsider = make_user(session, standard_account=True)
    marketplace.owner_user_id = owner.id
    apply(session, marketplace, catalog("private-source"))
    skill = skills(session, marketplace)[0]
    session.commit()
    with client_for(outsider, session) as client:
        assert client.get(f"/skills/{skill.id}").status_code == 404
        response = client.get("/skills")
        assert response.status_code == 200, response.text
        assert str(skill.id) not in {row["id"] for row in response.json()["customs"]}
