from __future__ import annotations

from sqlalchemy.orm import Session

from onyx.db.external_app import get_connectable_apps_for_user
from onyx.server.features.build.sandbox.util.agent_instructions import (
    build_connectable_apps_list,
)
from tests.external_dependency_unit.craft.db_helpers import make_external_app
from tests.external_dependency_unit.craft.db_helpers import make_skill
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.craft.db_helpers import make_user_credential

# auth_template value carrying a user-supplied placeholder.
_USER_TOKEN_TEMPLATE = {"Authorization": "Bearer {token}"}


def test_lists_only_unconnected_apps_and_renders_them(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = make_user(db_session, email_prefix="connectable")

    # Connectable: public, needs a user token the org hasn't pre-filled.
    make_external_app(
        db_session,
        skill=make_skill(db_session, slug="needs-setup", is_public=True),
        auth_template=_USER_TOKEN_TEMPLATE,
    )
    # Connected: the user already stored the token.
    connected = make_external_app(
        db_session,
        skill=make_skill(db_session, slug="already-connected", is_public=True),
        auth_template=_USER_TOKEN_TEMPLATE,
    )
    make_user_credential(
        db_session, app=connected, user=user, user_credentials={"token": "secret"}
    )
    # Org-credentialed: org pre-fills the token, so there's nothing to set up.
    make_external_app(
        db_session,
        skill=make_skill(db_session, slug="org-filled", is_public=True),
        auth_template=_USER_TOKEN_TEMPLATE,
        organization_credentials={"token": "shared"},
    )
    # Disabled: never offered, regardless of credentials.
    make_external_app(
        db_session,
        skill=make_skill(db_session, slug="disabled-app", enabled=False),
        auth_template=_USER_TOKEN_TEMPLATE,
    )
    # Not visible: non-public and not granted to this user — must be excluded, or
    # the user would connect a skill that never injects into their sandbox.
    make_external_app(
        db_session,
        skill=make_skill(db_session, slug="hidden-app", is_public=False),
        auth_template=_USER_TOKEN_TEMPLATE,
    )
    db_session.commit()

    slugs = {app.skill.slug for app in get_connectable_apps_for_user(db_session, user)}

    assert "needs-setup" in slugs
    assert "already-connected" not in slugs
    assert "org-filled" not in slugs
    assert "disabled-app" not in slugs
    assert "hidden-app" not in slugs

    apps_list = build_connectable_apps_list(
        get_connectable_apps_for_user(db_session, user)
    )
    assert "- **needs-setup**" in apps_list
    assert "hidden-app" not in apps_list
