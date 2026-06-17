"""External-app vs skill-endpoint boundary.

External-app-backed skills are managed via the external-apps API; the
skills API never lists or mutates them. The sandbox-injection path is
*different* — it includes the authenticated external-app skills the
user has connected, so the agent's workspace gets the right files.

Two contracts under test:

1. The skills endpoint (``list_skills_for_user`` / ``fetch_skill_for_user``
   / ``fetch_skill_for_user_by_slug``) **never** returns an external-app
   skill, regardless of whether the user has authenticated for it.
2. The sandbox-injection path (``list_skills_for_sandbox_injection``)
   includes external-app skills the user has authenticated for and
   excludes the ones they haven't.

Regular skills (no backing ``ExternalApp`` row) are unaffected by
either filter and remain subject only to the existing ``enabled`` +
sharing-scope rules.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.db.skill import fetch_skill_for_user
from onyx.db.skill import fetch_skill_for_user_by_slug
from onyx.db.skill import list_skills_for_sandbox_injection
from onyx.db.skill import list_skills_for_user
from tests.external_dependency_unit.craft._test_helpers import make_external_app
from tests.external_dependency_unit.craft._test_helpers import make_skill
from tests.external_dependency_unit.craft._test_helpers import make_user
from tests.external_dependency_unit.craft._test_helpers import make_user_credential

# Required keys are top-level auth_template keys not covered by
# organization_credentials (mirrors `is_user_authenticated_for_app`).
_AUTH_TEMPLATE = {"token": "{token}", "account": "{account}"}
_FULL_CREDS = {"token": "t", "account": "a"}


def _endpoint_ids(user: User, db_session: Session) -> set:
    return {s.id for s in list_skills_for_user(user, db_session)}


def _injectable_ids(user: User, db_session: Session) -> set:
    return {s.id for s in list_skills_for_sandbox_injection(user, db_session)}


# ── skills endpoint NEVER shows external-app skills ────────────────


def test_skills_endpoint_hides_external_app_when_unauthenticated(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    make_external_app(db_session, skill=skill, auth_template=_AUTH_TEMPLATE)

    assert skill.id not in _endpoint_ids(user, db_session)
    assert fetch_skill_for_user(skill.id, user, db_session) is None
    assert fetch_skill_for_user_by_slug(skill.slug, user, db_session) is None


def test_skills_endpoint_hides_external_app_even_when_authenticated(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """The skills endpoint is the seam for *skills*; external apps are
    managed via the external-apps API and must never appear here,
    regardless of whether the user has filled in their credentials.
    This is also what makes them immutable from the skills endpoint —
    mutation routes look up the row via these fetch helpers, so a
    ``None`` here means PATCH/DELETE on an external-app skill 404s."""
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    app = make_external_app(db_session, skill=skill, auth_template=_AUTH_TEMPLATE)
    make_user_credential(db_session, app=app, user=user, user_credentials=_FULL_CREDS)

    assert skill.id not in _endpoint_ids(user, db_session)
    assert fetch_skill_for_user(skill.id, user, db_session) is None
    assert fetch_skill_for_user_by_slug(skill.slug, user, db_session) is None


def test_skills_endpoint_hides_external_app_with_no_required_keys(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """Even when the external app needs no user credentials at all, it
    still doesn't belong in the skills endpoint."""
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    make_external_app(db_session, skill=skill, auth_template={})

    assert skill.id not in _endpoint_ids(user, db_session)


def test_regular_skill_still_visible_in_skills_endpoint(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """A skill with no backing ExternalApp is unaffected by the filter."""
    user = make_user(db_session)
    regular = make_skill(db_session, is_public=True, slug="plain-skill")
    gated = make_skill(db_session, is_public=True, slug="ext-gated")
    make_external_app(db_session, skill=gated, auth_template=_AUTH_TEMPLATE)

    visible = _endpoint_ids(user, db_session)
    assert regular.id in visible
    assert gated.id not in visible


# ── sandbox injection respects per-user authentication ─────────────


def test_sandbox_injection_includes_authenticated_external_app(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """The sandbox-push path picks up the authenticated external-app
    skill even though the skills endpoint hides it — the agent gets
    the files it needs to use the connected app."""
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    app = make_external_app(db_session, skill=skill, auth_template=_AUTH_TEMPLATE)
    make_user_credential(db_session, app=app, user=user, user_credentials=_FULL_CREDS)

    assert skill.id in _injectable_ids(user, db_session)


def test_sandbox_injection_excludes_unauthenticated_external_app(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    make_external_app(db_session, skill=skill, auth_template=_AUTH_TEMPLATE)

    assert skill.id not in _injectable_ids(user, db_session)


def test_sandbox_injection_excludes_partial_credentials(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    skill = make_skill(db_session, is_public=True)
    app = make_external_app(db_session, skill=skill, auth_template=_AUTH_TEMPLATE)
    make_user_credential(
        db_session, app=app, user=user, user_credentials={"token": "t"}
    )  # missing "account"

    assert skill.id not in _injectable_ids(user, db_session)


def test_sandbox_injection_includes_external_app_with_no_required_keys(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """An external app whose required keys are all org-supplied (or
    whose auth_template is empty) needs no per-user credential row to
    be considered authenticated."""
    user = make_user(db_session)

    s_empty = make_skill(db_session, is_public=True, slug="ext-empty-template")
    make_external_app(db_session, skill=s_empty, auth_template={})

    s_org_filled = make_skill(db_session, is_public=True, slug="ext-org-fills-all")
    make_external_app(
        db_session,
        skill=s_org_filled,
        auth_template={"token": "static"},
        organization_credentials={"token": "from-org"},
    )

    injectable = _injectable_ids(user, db_session)
    assert s_empty.id in injectable
    assert s_org_filled.id in injectable


def test_sandbox_injection_includes_regular_skills(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """Sandbox push covers regular skills exactly the same way the
    skills endpoint does — only the external-app handling differs."""
    user = make_user(db_session)
    regular = make_skill(db_session, is_public=True, slug="plain-included")

    assert regular.id in _injectable_ids(user, db_session)
