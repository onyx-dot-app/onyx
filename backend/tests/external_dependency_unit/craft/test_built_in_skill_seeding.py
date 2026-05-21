"""Tests for the built-in skill bootstrap path"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.skill import fetch_skill_for_user
from onyx.db.skill import list_skills_for_user
from onyx.db.skill import seed_built_in_skills
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.api import _ensure_custom
from onyx.skills import built_in as built_in_module
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.built_in import BuiltInSkillDefinition
from tests.external_dependency_unit.craft._test_helpers import make_built_in_skill_row
from tests.external_dependency_unit.craft._test_helpers import make_skill


@pytest.fixture(autouse=True)
def _isolate_built_in_skill_rows(
    db_session: Session,
) -> Generator[None, None, None]:
    """Drop any built-in rows before and after each test so admin-edits
    from one test don't bleed into the next. The seeder is idempotent
    and gets re-run inside each test that needs it."""
    db_session.execute(delete(Skill).where(Skill.built_in_skill_id.is_not(None)))
    db_session.commit()
    yield
    db_session.execute(delete(Skill).where(Skill.built_in_skill_id.is_not(None)))
    db_session.commit()


def _seeded(db_session: Session, built_in_skill_id: str) -> Skill:
    """The seeder produces one default row per built-in with
    ``slug == built_in_skill_id``. Look up by slug since
    ``built_in_skill_id`` is no longer unique (other code paths can
    add additional rows referencing the same built-in)."""
    row = db_session.scalar(select(Skill).where(Skill.slug == built_in_skill_id))
    assert row is not None, f"expected seeded row for {built_in_skill_id}"
    return row


class TestSeed:
    def test_seeder_inserts_one_row_per_codified_built_in(
        self, db_session: Session
    ) -> None:
        seed_built_in_skills(db_session)
        db_session.commit()

        for built_in_skill_id in BUILT_IN_SKILLS:
            row = _seeded(db_session, built_in_skill_id)
            assert row.slug == built_in_skill_id
            assert row.bundle_file_id is None
            assert row.bundle_sha256 is None
            assert row.is_public is True
            assert row.enabled is True

    def test_seeder_is_idempotent(self, db_session: Session) -> None:
        seed_built_in_skills(db_session)
        db_session.commit()
        first_ids = {
            s.id
            for s in db_session.scalars(
                select(Skill).where(Skill.built_in_skill_id.is_not(None))
            )
        }

        seed_built_in_skills(db_session)
        db_session.commit()
        second_ids = {
            s.id
            for s in db_session.scalars(
                select(Skill).where(Skill.built_in_skill_id.is_not(None))
            )
        }

        assert first_ids == second_ids

    def test_seeder_refreshes_name_and_description_from_disk(
        self,
        db_session: Session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Edits to a built-in's SKILL.md frontmatter must propagate to
        the row on the next boot — matches what ``replace_skill_bundle``
        does for custom skills. Simulated by pointing the definition at
        a tmp_path with a freshly-written SKILL.md."""
        seed_built_in_skills(db_session)
        db_session.commit()
        row = _seeded(db_session, "pptx")
        original_id = row.id

        fake_source = tmp_path / "pptx"
        fake_source.mkdir()
        (fake_source / "SKILL.md").write_text(
            "---\nname: Refreshed Name\ndescription: Refreshed description\n---\n"
        )
        monkeypatch.setitem(
            built_in_module.BUILT_IN_SKILLS,
            "pptx",
            BuiltInSkillDefinition(
                built_in_skill_id="pptx",
                has_template=False,
                source_dir=fake_source,
            ),
        )

        seed_built_in_skills(db_session)
        db_session.commit()

        db_session.refresh(row)
        assert row.id == original_id  # same row, just updated
        assert row.name == "Refreshed Name"
        assert row.description == "Refreshed description"

    def test_seeder_preserves_lifecycle_state(
        self,
        db_session: Session,
    ) -> None:
        """Re-seeding must not clobber lifecycle fields. Built-ins are
        codified as ``is_public=True, enabled=True``, but if a future
        flow ever toggles them in the DB, re-seeding shouldn't undo it."""
        seed_built_in_skills(db_session)
        db_session.commit()
        row = _seeded(db_session, "pptx")

        # Simulate a non-default lifecycle state on the seeded row.
        row.enabled = False
        row.is_public = False
        db_session.commit()

        seed_built_in_skills(db_session)
        db_session.commit()
        db_session.refresh(row)

        assert row.enabled is False
        assert row.is_public is False


class TestAvailabilityGate:
    def test_unavailable_built_in_is_filtered_from_user_listing(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seed_built_in_skills(db_session)
        db_session.commit()

        gated_id = "pptx"
        original = built_in_module.BUILT_IN_SKILLS[gated_id]
        monkeypatch.setitem(
            built_in_module.BUILT_IN_SKILLS,
            gated_id,
            BuiltInSkillDefinition(
                built_in_skill_id=original.built_in_skill_id,
                has_template=original.has_template,
                source_dir=original.source_dir,
                is_available=lambda _: False,
                unavailable_reason="dependency missing in test",
            ),
        )

        visible = {
            s.built_in_skill_id for s in list_skills_for_user(test_user, db_session)
        }
        assert gated_id not in visible

    def test_available_built_in_is_visible(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        seed_built_in_skills(db_session)
        db_session.commit()

        visible_built_ins = {
            s.built_in_skill_id
            for s in list_skills_for_user(test_user, db_session)
            if s.built_in_skill_id is not None
        }
        assert set(BUILT_IN_SKILLS) <= visible_built_ins

    def test_unavailable_built_in_cannot_be_fetched_by_id(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seed_built_in_skills(db_session)
        db_session.commit()

        gated_id = "pptx"
        row = _seeded(db_session, gated_id)
        original = built_in_module.BUILT_IN_SKILLS[gated_id]
        monkeypatch.setitem(
            built_in_module.BUILT_IN_SKILLS,
            gated_id,
            BuiltInSkillDefinition(
                built_in_skill_id=original.built_in_skill_id,
                has_template=original.has_template,
                source_dir=original.source_dir,
                is_available=lambda _: False,
            ),
        )

        assert fetch_skill_for_user(row.id, test_user, db_session) is None


class TestBuiltInIsImmutable:
    """Built-in skill rows reject every admin mutation path: PATCH,
    bundle-replace, grants-replace, delete. Enforcement lives at the
    API layer via ``_ensure_custom`` and the discriminator is
    ``built_in_skill_id IS NOT NULL``."""

    def test_ensure_custom_rejects_built_in_rows(self, db_session: Session) -> None:
        seed_built_in_skills(db_session)
        db_session.commit()
        row = _seeded(db_session, "pptx")

        with pytest.raises(OnyxError, match="cannot be modified"):
            _ensure_custom(row)

    def test_ensure_custom_accepts_custom_rows(self, db_session: Session) -> None:
        custom = make_skill(db_session, slug=f"custom-{uuid4().hex[:8]}")
        db_session.commit()

        _ensure_custom(custom)  # no raise


class TestNonUniqueBuiltInId:
    def test_multiple_rows_can_share_a_built_in_skill_id(
        self, db_session: Session
    ) -> None:
        """``built_in_skill_id`` is not unique — a single built-in can
        back multiple rows (different slugs / sharing scopes). Slug
        remains the natural unique key."""
        # Default seeded row: slug == built_in_skill_id == "pptx".
        seed_built_in_skills(db_session)
        db_session.commit()

        # A second row references the same built-in but uses a
        # different slug (e.g. team-specific instance).
        make_built_in_skill_row(
            db_session,
            built_in_skill_id="pptx",
            slug="pptx-team-a",
            name="pptx (team A)",
            is_public=False,
        )
        db_session.commit()

        matches = list(
            db_session.scalars(select(Skill).where(Skill.built_in_skill_id == "pptx"))
        )
        assert len(matches) == 2
        assert {s.slug for s in matches} == {"pptx", "pptx-team-a"}

    def test_seeder_does_not_duplicate_when_extra_rows_exist(
        self, db_session: Session
    ) -> None:
        """Re-running the seeder when additional rows for the same
        built-in already exist must not add another default row, must
        not delete the extras."""
        seed_built_in_skills(db_session)
        db_session.commit()
        make_built_in_skill_row(
            db_session, built_in_skill_id="pptx", slug="pptx-team-a"
        )
        db_session.commit()

        seed_built_in_skills(db_session)
        db_session.commit()

        slugs = {
            s.slug
            for s in db_session.scalars(
                select(Skill).where(Skill.built_in_skill_id == "pptx")
            )
        }
        assert slugs == {"pptx", "pptx-team-a"}


class TestSchemaInvariant:
    def test_built_in_row_has_null_bundle_fields(self, db_session: Session) -> None:
        """``ck_skill_definition_source`` enforces XOR — built-in rows
        keep ``bundle_file_id`` NULL, custom rows keep it set."""
        seed_built_in_skills(db_session)
        db_session.commit()
        row = _seeded(db_session, "company-search")
        assert row.bundle_file_id is None
        assert row.bundle_sha256 is None

    def test_metadata_round_trips_to_frontmatter(self, db_session: Session) -> None:
        """The DB ``name`` matches the on-disk SKILL.md frontmatter for
        each seeded built-in — the seeder reads frontmatter authoritatively."""
        seed_built_in_skills(db_session)
        db_session.commit()
        for built_in_skill_id, definition in BUILT_IN_SKILLS.items():
            row = _seeded(db_session, built_in_skill_id)
            disk_name, disk_description = definition.read_metadata()
            assert row.name == disk_name
            assert row.description == disk_description

    def test_source_dir_resolves_under_skills_template_path(self) -> None:
        for definition in BUILT_IN_SKILLS.values():
            assert isinstance(definition.source_dir, Path)
            assert definition.source_dir.is_dir()
