"""Tests for built-in skill *row* behavior.

The ``skill`` rows for built-ins are seeded by the
``skill_built_in_id_discriminator`` migration — migrations are the source
of truth and there is no boot-time seeder. These tests cover the runtime
behaviors that depend on those rows plus the codified ``BUILT_IN_SKILLS``:
availability gating, admin-immutability and the non-unique
``built_in_skill_id``. Rows are inserted
directly via ``make_built_in_skill_row`` so each test is self-contained
and order-independent."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.db.models import Skill, User
from onyx.db.skill import (
    fetch_editable_skill,
    fetch_skill,
    list_runtime_skills_for_user,
    list_skills,
)
from onyx.skills.built_in import (
    BUILT_IN_SKILLS,
    EXTERNAL_APP_SKILL_ID_TO_APP_TYPE,
    BuiltInSkillDefinition,
)
from tests.external_dependency_unit.craft.db_helpers import (
    make_built_in_skill_row,
    make_skill,
)


@pytest.fixture(autouse=True)
def _isolate_built_in_skill_rows(
    db_session: Session,
) -> Generator[None, None, None]:
    """Start and end each test with no built-in rows so the
    migration-seeded canonical rows don't interfere; each test inserts
    exactly the rows it needs."""
    db_session.execute(delete(Skill).where(Skill.built_in_skill_id.is_not(None)))
    db_session.commit()
    yield
    db_session.execute(delete(Skill).where(Skill.built_in_skill_id.is_not(None)))
    db_session.commit()


def _seed_canonical(db_session: Session) -> None:
    """Insert one default row per codified built-in, mirroring what the
    migration seeds (name == built_in_skill_id, public, enabled)."""
    for built_in_skill_id in BUILT_IN_SKILLS:
        make_built_in_skill_row(db_session, built_in_skill_id=built_in_skill_id)
    db_session.commit()


def _row(db_session: Session, built_in_skill_id: str) -> Skill:
    row = db_session.scalar(select(Skill).where(Skill.name == built_in_skill_id))
    assert row is not None, f"expected built-in row for {built_in_skill_id}"
    return row


class TestAvailabilityGate:
    def test_unavailable_built_in_is_filtered_from_user_listing(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_canonical(db_session)

        gated_id = "pptx"
        original = BUILT_IN_SKILLS[gated_id]
        monkeypatch.setitem(
            BUILT_IN_SKILLS,
            gated_id,
            BuiltInSkillDefinition(
                built_in_skill_id=original.built_in_skill_id,
                is_available=lambda _: False,
                unavailable_reason="dependency missing in test",
            ),
        )

        visible = {
            s.built_in_skill_id
            for s in list_skills(
                user=test_user,
                db_session=db_session,
            )
            if isinstance(s, Skill)
        }
        assert gated_id not in visible

    def test_available_built_in_is_visible(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        _seed_canonical(db_session)

        visible_built_ins = {
            s.built_in_skill_id
            for s in list_skills(
                user=test_user,
                db_session=db_session,
            )
            if isinstance(s, Skill)
        }
        # Some built-ins gate on environment availability (e.g. image-generation
        # needs a configured provider); only those available here must be visible.
        # An app built-in shows only to a user who runs a plugin of its preset.
        available_built_ins = {
            built_in_skill_id
            for built_in_skill_id, definition in BUILT_IN_SKILLS.items()
            if definition.is_available(db_session)
            and built_in_skill_id not in EXTERNAL_APP_SKILL_ID_TO_APP_TYPE
        }
        assert available_built_ins <= visible_built_ins

    def test_browser_built_in_gated_on_enable_browser(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_canonical(db_session)

        monkeypatch.setattr("onyx.skills.built_in.ENABLE_BROWSER", False)
        off = {
            s.built_in_skill_id
            for s in list_runtime_skills_for_user(
                user=test_user,
                db_session=db_session,
            )
        }
        assert "browser" not in off

        monkeypatch.setattr("onyx.skills.built_in.ENABLE_BROWSER", True)
        on = {
            s.built_in_skill_id
            for s in list_runtime_skills_for_user(
                user=test_user,
                db_session=db_session,
            )
        }
        assert "browser" in on

    def test_unavailable_built_in_cannot_be_fetched_by_id(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_canonical(db_session)

        gated_id = "pptx"
        row = _row(db_session, gated_id)
        original = BUILT_IN_SKILLS[gated_id]
        monkeypatch.setitem(
            BUILT_IN_SKILLS,
            gated_id,
            BuiltInSkillDefinition(
                built_in_skill_id=original.built_in_skill_id,
                is_available=lambda _: False,
            ),
        )

        assert (
            fetch_skill(
                row.id,
                user=test_user,
                db_session=db_session,
            )
            is None
        )


class TestBuiltInIsImmutable:
    """Built-in skill rows are not editable custom skills."""

    def test_edit_fetch_rejects_built_in_rows(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        row = make_built_in_skill_row(db_session, built_in_skill_id="pptx")
        db_session.commit()

        assert (
            fetch_editable_skill(
                row.id,
                user=test_user,
                db_session=db_session,
            )
            is None
        )

    def test_edit_fetch_accepts_owned_custom_rows(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        custom = make_skill(
            db_session,
            name=f"custom-{uuid4().hex[:8]}",
            author_user_id=test_user.id,
        )
        db_session.commit()

        skill = fetch_editable_skill(
            custom.id,
            user=test_user,
            db_session=db_session,
        )
        assert skill is not None
        assert skill.id == custom.id


class TestNonUniqueBuiltInId:
    def test_multiple_rows_can_share_a_built_in_skill_id(
        self, db_session: Session
    ) -> None:
        """``built_in_skill_id`` is not unique — a single built-in can
        back multiple rows with different canonical names."""
        make_built_in_skill_row(db_session, built_in_skill_id="pptx")
        make_built_in_skill_row(
            db_session,
            built_in_skill_id="pptx",
            name="pptx-team-a",
        )
        db_session.commit()

        matches = list(
            db_session.scalars(select(Skill).where(Skill.built_in_skill_id == "pptx"))
        )
        assert len(matches) == 2
        assert {s.name for s in matches} == {"pptx", "pptx-team-a"}


class TestBuiltInSourceDirectory:
    def test_source_dir_resolves_under_skills_template_path(self) -> None:
        for definition in BUILT_IN_SKILLS.values():
            assert isinstance(definition.source_dir, Path)
            assert definition.source_dir.is_dir()
