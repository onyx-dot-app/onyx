"""Ext-dep tests for ``build_skills_fileset_for_user``."""

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
from onyx.skills import built_in as built_in_module
from onyx.skills.built_in import BuiltInSkillDefinition
from onyx.skills.push import build_skills_fileset_for_user
from tests.external_dependency_unit.craft._test_helpers import add_user_to_group
from tests.external_dependency_unit.craft._test_helpers import make_built_in_skill_row
from tests.external_dependency_unit.craft._test_helpers import make_cc_pair
from tests.external_dependency_unit.craft._test_helpers import make_group
from tests.external_dependency_unit.craft._test_helpers import reset_built_in_skill_row

_FRONTMATTER = "---\nname: {slug}\ndescription: {slug}\n---\n"


def _write_skill_dir(
    skills_root: Path,
    skill_id: str,
    *,
    template_body: str | None = None,
    extra_files: dict[str, str] | None = None,
) -> None:
    """Write a built-in's on-disk content at ``skills_root/<skill_id>`` — the
    same ``SKILLS_TEMPLATE_PATH/<built_in_skill_id>`` layout production uses, so
    the definition's computed ``source_dir`` resolves here once the caller has
    redirected ``SKILLS_TEMPLATE_PATH`` at ``skills_root``.
    """
    source_dir = skills_root / skill_id
    source_dir.mkdir(parents=True)
    if template_body is not None:
        (source_dir / "SKILL.md.template").write_text(template_body, encoding="utf-8")
    else:
        (source_dir / "SKILL.md").write_text(
            _FRONTMATTER.format(slug=skill_id), encoding="utf-8"
        )
    for rel, content in (extra_files or {}).items():
        path = source_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _register_built_in(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    skills_root: Path,
    *,
    extra_files: dict[str, str] | None = None,
    template_body: str | None = None,
) -> str:
    """Register a fresh synthetic built-in (definition + Skill row) whose
    content lives under ``skills_root/<id>``, redirecting ``SKILLS_TEMPLATE_PATH``
    so its computed ``source_dir`` resolves there. Returns the synthetic
    ``built_in_skill_id`` (also the slug and on-disk dir name).
    """
    monkeypatch.setattr(built_in_module, "SKILLS_TEMPLATE_PATH", str(skills_root))
    built_in_skill_id = f"test-builtin-{uuid4().hex[:8]}"
    _write_skill_dir(
        skills_root,
        built_in_skill_id,
        template_body=template_body,
        extra_files=extra_files,
    )
    monkeypatch.setitem(
        built_in_module.BUILT_IN_SKILLS,
        built_in_skill_id,
        BuiltInSkillDefinition(built_in_skill_id=built_in_skill_id),
    )
    make_built_in_skill_row(db_session, built_in_skill_id=built_in_skill_id)
    db_session.commit()
    return built_in_skill_id


class TestBuiltInFromDisk:
    def test_static_built_in_files_are_included_under_slug_prefix(
        self,
        tmp_path: Path,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        slug = _register_built_in(
            monkeypatch,
            db_session,
            tmp_path,
            extra_files={"scripts/preview.py": "print('hi')"},
        )

        files = build_skills_fileset_for_user(test_user, db_session)

        assert f"name: {slug}".encode() in files[f"{slug}/SKILL.md"]
        assert files[f"{slug}/scripts/preview.py"] == b"print('hi')"

    def test_excluded_dirs_and_dotfiles_are_skipped(
        self,
        tmp_path: Path,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        slug = _register_built_in(
            monkeypatch,
            db_session,
            tmp_path,
            extra_files={
                "__pycache__/cached.pyc": "junk",
                ".DS_Store": "junk",
                "scripts/.hidden": "junk",
            },
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
        # Redirect SKILLS_TEMPLATE_PATH at tmp_path and write the template under
        # company-search/ — the registry's existing definition computes its
        # source_dir from there, so no definition swap is needed. reset_* is
        # idempotent against the migration-seeded canonical row.
        monkeypatch.setattr(built_in_module, "SKILLS_TEMPLATE_PATH", str(tmp_path))
        _write_skill_dir(tmp_path, "company-search", template_body=template_body)
        reset_built_in_skill_row(db_session, built_in_skill_id="company-search")
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
        monkeypatch.setattr(built_in_module, "SKILLS_TEMPLATE_PATH", str(tmp_path))
        _write_skill_dir(
            tmp_path,
            "company-search",
            template_body=template_body,
            extra_files={"scripts/search.py": "print('search')"},
        )
        reset_built_in_skill_row(db_session, built_in_skill_id="company-search")
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
