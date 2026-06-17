"""Consume-time rendering of a persona's attached skills for NORMAL chat.

Exercises the prompt-assembly path directly (no running app, no LLM call):
``fetch_persona_skills_visible_to_user`` (the intersection-only security gate)
feeding ``render_attached_skills_section`` (the compact INDEX in the system
prompt) and ``render_skill_body`` (the on-demand full body, fetched by
LoadSkillTool). Asserts:

- (a) the author's attached skill appears in the index (name + slug +
  description + the load_skill instruction), with NO full body inlined;
- (b) a different user on the same shared persona gets no section (private
  skill is silently dropped by the intersection gate);
- (c) ``render_skill_body`` returns the full SKILL.md body for a visible skill.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi_users.password import PasswordHelper
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.models import Persona
from onyx.db.models import Persona__Skill
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.db.skill import fetch_persona_skills_visible_to_user
from onyx.file_store.file_store import get_default_file_store
from onyx.skills.render import render_attached_skills_section
from onyx.skills.render import render_skill_body
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID


@pytest.fixture(autouse=True)
def _tenant_context() -> Iterator[None]:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def _make_user(db_session: Session) -> User:
    helper = PasswordHelper()
    user = User(
        id=uuid4(),
        email=f"skills_render_{uuid4().hex[:8]}@example.com",
        hashed_password=helper.hash(helper.generate()),
        is_active=True,
        is_verified=True,
        role=UserRole.BASIC,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _save_bundle(skill_md_body: str, slug: str) -> tuple[str, str]:
    """Pack ``SKILL.md`` into a zip, store it, return (file_id, sha256)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", skill_md_body)
    data = buf.getvalue()
    file_store = get_default_file_store()
    file_store.initialize()
    file_id = file_store.save_file(
        content=io.BytesIO(data),
        display_name=f"{slug}.zip",
        file_origin=FileOrigin.SKILL_BUNDLE,
        file_type="application/zip",
    )
    return file_id, hashlib.sha256(data).hexdigest()


def _make_custom_skill(
    db_session: Session,
    *,
    skill_md_body: str,
    author: User,
    is_public: bool = False,
) -> Skill:
    slug = f"render-skill-{uuid4().hex[:8]}"
    file_id, sha = _save_bundle(skill_md_body, slug)
    skill = Skill(
        id=uuid4(),
        slug=slug,
        name=f"Skill {slug}",
        description=f"Description for {slug}",
        bundle_file_id=file_id,
        bundle_sha256=sha,
        is_public=is_public,
        enabled=True,
        author_user_id=author.id,
    )
    db_session.add(skill)
    db_session.flush()
    return skill


def _make_persona_with_skills(
    db_session: Session, owner: User, skills: list[Skill]
) -> Persona:
    persona = Persona(
        name=f"render-persona-{uuid4().hex[:8]}",
        description="test persona",
        user_id=owner.id,
        is_public=True,
    )
    persona.skills = skills
    db_session.add(persona)
    db_session.flush()
    return persona


_AUTHOR_BODY = (
    "---\nname: tdd-helper\ndescription: Test driven helper\n---\n\n"
    "# TDD Helper\n\nALWAYS write a failing test first. "
    "UNIQUE_MARKER_AUTHOR_BODY_42\n"
)


class TestAttachedSkillsRender:
    def test_index_lists_skill_without_body(self, db_session: Session) -> None:
        author = _make_user(db_session)
        skill = _make_custom_skill(
            db_session, skill_md_body=_AUTHOR_BODY, author=author, is_public=False
        )
        persona = _make_persona_with_skills(db_session, author, [skill])

        visible = fetch_persona_skills_visible_to_user(persona, author, db_session)
        assert {s.id for s in visible} == {skill.id}

        section = render_attached_skills_section(visible)
        assert section is not None
        # Header + the index line (name + slug + description).
        assert "# Attached Skills" in section
        assert skill.name in section
        assert f"slug: {skill.slug}" in section
        assert skill.description in section
        # Instruction steering the model to the load_skill tool.
        assert "load_skill" in section
        # Crucially: NO full body inlined — only the index.
        assert "UNIQUE_MARKER_AUTHOR_BODY_42" not in section
        assert "<skill" not in section

    def test_other_user_on_shared_persona_does_not_see_private_skill(
        self, db_session: Session
    ) -> None:
        author = _make_user(db_session)
        other = _make_user(db_session)
        # Private skill (not public, no group grant): only the author can see it.
        skill = _make_custom_skill(
            db_session, skill_md_body=_AUTHOR_BODY, author=author, is_public=False
        )
        persona = _make_persona_with_skills(db_session, author, [skill])

        # Intersection keyed to the ACTING user (other), not the persona owner.
        visible = fetch_persona_skills_visible_to_user(persona, other, db_session)
        assert visible == []

        section = render_attached_skills_section(visible)
        # No visible skills → no section at all.
        assert section is None

    def test_render_skill_body_returns_full_body(self, db_session: Session) -> None:
        author = _make_user(db_session)
        skill = _make_custom_skill(
            db_session, skill_md_body=_AUTHOR_BODY, author=author, is_public=False
        )
        persona = _make_persona_with_skills(db_session, author, [skill])

        visible = fetch_persona_skills_visible_to_user(persona, author, db_session)
        assert {s.id for s in visible} == {skill.id}

        body = render_skill_body(visible[0], db_session, author)
        assert body is not None
        # The full SKILL.md body — the part NOT in the index.
        assert "UNIQUE_MARKER_AUTHOR_BODY_42" in body
        assert "ALWAYS write a failing test first" in body

    def test_returns_none_when_no_skills(self) -> None:
        assert render_attached_skills_section([]) is None


@pytest.fixture(autouse=True)
def _cleanup_persona_skill_join(db_session: Session) -> Iterator[None]:
    """Belt-and-braces: drop any persona__skill join rows on teardown so a
    failed assertion mid-test doesn't leave dangling associations."""
    yield
    db_session.execute(delete(Persona__Skill))
    db_session.rollback()
