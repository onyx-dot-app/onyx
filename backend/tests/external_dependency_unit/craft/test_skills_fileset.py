"""Ext-dep tests for ``build_skills_fileset_for_user``.

The test pattern is:
- write a tmp_path "skill directory" with SKILL.md (and optional siblings)
- monkeypatch a fresh entry into ``BUILT_IN_SKILLS`` whose ``source_dir``
  points at the tmp_path
- insert a ``Skill`` row referencing that ``built_in_skill_id``
- call ``build_skills_fileset_for_user`` and assert on the rendered fileset

This keeps each test fully isolated from on-disk built-ins seeded by
``setup_postgres`` — we use synthetic ``built_in_skill_id`` values that
never collide with the canonical pptx / image-generation /
company-search rows.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.models import UserGroup
from onyx.db.skill import seed_built_in_skills
from onyx.skills import built_in as built_in_module
from onyx.skills.built_in import BuiltInSkillDefinition
from onyx.skills.push import build_skills_fileset_for_user
from tests.external_dependency_unit.craft._test_helpers import add_user_to_group
from tests.external_dependency_unit.craft._test_helpers import make_built_in_skill_row
from tests.external_dependency_unit.craft._test_helpers import make_cc_pair
from tests.external_dependency_unit.craft._test_helpers import make_group

_FRONTMATTER = "---\nname: {slug}\ndescription: {slug}\n---\n"


def _register_built_in(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    *,
    source_dir: Path,
    has_template: bool,
) -> str:
    """Register a fresh built-in definition + Skill row for one test.

    Returns the synthetic ``built_in_skill_id`` (also used as slug).
    """
    built_in_skill_id = f"test-builtin-{uuid4().hex[:8]}"
    definition = BuiltInSkillDefinition(
        built_in_skill_id=built_in_skill_id,
        has_template=has_template,
        source_dir=source_dir,
    )
    monkeypatch.setitem(built_in_module.BUILT_IN_SKILLS, built_in_skill_id, definition)
    make_built_in_skill_row(db_session, built_in_skill_id=built_in_skill_id)
    db_session.commit()
    return built_in_skill_id


def _write_static_dir(
    tmp_path: Path,
    slug: str,
    extra_files: dict[str, str] | None = None,
) -> Path:
    """Create a source dir under ``tmp_path`` with SKILL.md + optional siblings."""
    source_dir = tmp_path / slug
    source_dir.mkdir(parents=True)
    (source_dir / "SKILL.md").write_text(
        _FRONTMATTER.format(slug=slug), encoding="utf-8"
    )
    for rel, content in (extra_files or {}).items():
        path = source_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return source_dir


def _write_template_dir(
    tmp_path: Path,
    slug: str,
    *,
    template_body: str,
    extra_files: dict[str, str] | None = None,
) -> Path:
    source_dir = tmp_path / slug
    source_dir.mkdir(parents=True)
    (source_dir / "SKILL.md.template").write_text(template_body, encoding="utf-8")
    for rel, content in (extra_files or {}).items():
        path = source_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return source_dir


class TestBuiltInFromDisk:
    def test_static_built_in_files_are_included_under_slug_prefix(
        self,
        tmp_path: Path,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        source = _write_static_dir(
            tmp_path, "pptx", {"scripts/preview.py": "print('hi')"}
        )
        slug = _register_built_in(
            monkeypatch, db_session, source_dir=source, has_template=False
        )

        files = build_skills_fileset_for_user(test_user, db_session)

        assert b"name: pptx" in files[f"{slug}/SKILL.md"]
        assert files[f"{slug}/scripts/preview.py"] == b"print('hi')"

    def test_excluded_dirs_and_dotfiles_are_skipped(
        self,
        tmp_path: Path,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        source = _write_static_dir(
            tmp_path,
            "pptx",
            {
                "__pycache__/cached.pyc": "junk",
                ".DS_Store": "junk",
                "scripts/.hidden": "junk",
            },
        )
        slug = _register_built_in(
            monkeypatch, db_session, source_dir=source, has_template=False
        )

        files = build_skills_fileset_for_user(test_user, db_session)

        assert f"{slug}/SKILL.md" in files
        assert f"{slug}/__pycache__/cached.pyc" not in files
        assert f"{slug}/.DS_Store" not in files
        assert f"{slug}/scripts/.hidden" not in files


class TestBuiltInTemplate:
    """Templated built-ins (company-search) get their SKILL.md rendered
    per-user. The renderer dispatches on ``built_in_skill_id``, so the
    synthetic slug needs to match a known renderer — here we point at
    ``company-search`` by directly seeding that row instead of a synthetic."""

    def test_template_built_in_is_rendered_per_user(
        self,
        tmp_path: Path,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        template_body = (
            f"{_FRONTMATTER.format(slug='company-search')}"
            "Sources:\n{{AVAILABLE_SOURCES_SECTION}}\n"
        )
        source = _write_template_dir(
            tmp_path, "company-search", template_body=template_body
        )
        # Redirect the company-search definition at the tmp_path source
        # AND seed the matching row — setup_postgres is not invoked in
        # this test harness.
        monkeypatch.setitem(
            built_in_module.BUILT_IN_SKILLS,
            "company-search",
            BuiltInSkillDefinition(
                built_in_skill_id="company-search",
                has_template=True,
                source_dir=source,
            ),
        )
        seed_built_in_skills(db_session)
        db_session.commit()
        make_cc_pair(db_session, DocumentSource.SLACK)

        files = build_skills_fileset_for_user(test_user, db_session)

        rendered = files["company-search/SKILL.md"].decode("utf-8")
        assert "{{AVAILABLE_SOURCES_SECTION}}" not in rendered
        assert "slack" in rendered

    def test_template_built_in_includes_static_siblings(
        self,
        tmp_path: Path,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        template_body = (
            f"{_FRONTMATTER.format(slug='company-search')}"
            "{{AVAILABLE_SOURCES_SECTION}}\n"
        )
        source = _write_template_dir(
            tmp_path,
            "company-search",
            template_body=template_body,
            extra_files={"scripts/search.py": "print('search')"},
        )
        monkeypatch.setitem(
            built_in_module.BUILT_IN_SKILLS,
            "company-search",
            BuiltInSkillDefinition(
                built_in_skill_id="company-search",
                has_template=True,
                source_dir=source,
            ),
        )
        seed_built_in_skills(db_session)
        db_session.commit()
        make_cc_pair(db_session, DocumentSource.GOOGLE_DRIVE)

        files = build_skills_fileset_for_user(test_user, db_session)

        assert files["company-search/scripts/search.py"] == b"print('search')"
        rendered = files["company-search/SKILL.md"].decode("utf-8")
        assert "google_drive" in rendered
        # The raw .template is never shipped — only the rendered output.
        assert "company-search/SKILL.md.template" not in files


class TestCustomSkillFileset:
    def test_custom_bundle_entries_are_added_under_their_slug(
        self,
        db_session: Session,
        test_user: User,
        seeded_skill: Callable[..., Skill],
    ) -> None:
        # Custom skills require a group grant to be visible to a non-admin
        # user. Set up: user is in group ``team``; skill is granted to
        # ``team``; the bundle holds two files. A uniquified slug avoids
        # collisions with leftover rows from prior partial runs.
        slug = f"my-custom-{uuid4().hex[:8]}"
        team_group: UserGroup = make_group(db_session)
        add_user_to_group(db_session, test_user, team_group)
        db_session.commit()

        seeded_skill(
            slug=slug,
            public=False,
            groups=[team_group],
            bundle_files={
                "SKILL.md": f"---\nname: {slug}\ndescription: c\n---\ncustom body",
                "nested/file.txt": "nested body",
            },
        )

        files = build_skills_fileset_for_user(test_user, db_session)

        assert b"custom body" in files[f"{slug}/SKILL.md"]
        assert files[f"{slug}/nested/file.txt"] == b"nested body"


class TestUnknownBuiltInRowIsSkipped:
    def test_row_with_unregistered_built_in_id_is_skipped(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        """A Skill row whose ``built_in_skill_id`` is missing from
        ``BUILT_IN_SKILLS`` (e.g. removed from code, row not cleaned up)
        should be skipped without breaking the rest of the fileset."""
        orphan_id = f"orphan-builtin-{uuid4().hex[:8]}"
        make_built_in_skill_row(db_session, built_in_skill_id=orphan_id)
        db_session.commit()

        # The function must not raise; the orphan row contributes no files.
        files = build_skills_fileset_for_user(test_user, db_session)
        assert not any(k.startswith(f"{orphan_id}/") for k in files)
