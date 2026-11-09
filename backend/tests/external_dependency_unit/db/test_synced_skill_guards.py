"""App updates preserve retired Skill associations without changing visibility."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.external_app import (
    get_skills_for_external_app,
    replace_custom_skill_associations__no_commit,
)
from onyx.db.models import ExternalApp__Skill, Skill
from tests.external_dependency_unit.craft.db_helpers import (
    make_external_app,
    make_skill,
    make_user,
)

pytestmark = pytest.mark.usefixtures("tenant_context", "enable_ee")


@pytest.mark.parametrize("include_retired", [False, True])
def test_app_replacement_preserves_retired_association(
    db_session: Session, include_retired: bool
) -> None:
    session = db_session
    owner = make_user(session, standard_account=True)
    target = make_skill(session, author_user_id=owner.id)
    app = make_external_app(session, skill=target, auth_template={})
    session.execute(
        update(Skill)
        .where(Skill.id == target.id)
        .values(retired_at=datetime.now(timezone.utc)),
        execution_options={"synchronize_session": False},
    )
    assert target.retired_at is None
    replacement = make_skill(session, name=target.name, author_user_id=owner.id)
    permission = target.public_permission
    affected = replace_custom_skill_associations__no_commit(
        session,
        external_app_id=app.id,
        skill_ids=[replacement.id, *([target.id] if include_retired else [])],
    )
    assert session.get(ExternalApp__Skill, (app.id, target.id)) is not None
    assert target.public_permission == permission
    assert [skill.id for skill in affected] == [replacement.id]
    assert [skill.id for skill in get_skills_for_external_app(session, app.id)] == [
        replacement.id
    ]
