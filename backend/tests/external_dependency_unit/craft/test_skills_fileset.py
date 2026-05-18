"""Ext-dep tests for ``build_skills_fileset_for_user`` (Cluster B prep)."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.models import UserGroup
from onyx.skills.push import build_skills_fileset_for_user
from onyx.skills.registry import BuiltinSkillRegistry
from tests.external_dependency_unit.craft._test_helpers import add_user_to_group
from tests.external_dependency_unit.craft._test_helpers import make_cc_pair
from tests.external_dependency_unit.craft._test_helpers import make_group

_FRONTMATTER = "---\nname: {slug}\ndescription: {slug}\n---\n"


@pytest.fixture(autouse=True)
def _reset_builtin_registry() -> Generator[None, None, None]:
    """Each test starts and ends with a clean registry — built-in skills are
    a process singleton and would leak across tests otherwise."""
    BuiltinSkillRegistry._reset_for_testing()
    yield
    BuiltinSkillRegistry._reset_for_testing()


def _write_static_builtin(
    tmp_path: Path,
    slug: str,
    extra_files: dict[str, str] | None = None,
) -> Path:
    """Create a builtin source dir under ``tmp_path`` with SKILL.md +
    additional files. Returns the source dir."""
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


def _write_template_builtin(
    tmp_path: Path,
    slug: str,
    *,
    template_body: str,
    extra_files: dict[str, str] | None = None,
) -> Path:
    """Create a template-style builtin source dir (with SKILL.md.template)."""
    source_dir = tmp_path / slug
    source_dir.mkdir(parents=True)
    (source_dir / "SKILL.md.template").write_text(template_body, encoding="utf-8")
    for rel, content in (extra_files or {}).items():
        path = source_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return source_dir


class TestBuiltinSkillFileset:
    def test_static_builtin_files_are_included_under_slug_prefix(
        self,
        tmp_path: Path,
        db_session: Session,
        test_user: User,
    ) -> None:
        source = _write_static_builtin(
            tmp_path, "pptx", {"scripts/preview.py": "print('hi')"}
        )
        BuiltinSkillRegistry.instance().register(slug="pptx", source_dir=source)

        files = build_skills_fileset_for_user(test_user, db_session)

        assert b"name: pptx" in files["pptx/SKILL.md"]
        assert files["pptx/scripts/preview.py"] == b"print('hi')"

    def test_excluded_dirs_and_dotfiles_are_skipped(
        self,
        tmp_path: Path,
        db_session: Session,
        test_user: User,
    ) -> None:
        source = _write_static_builtin(
            tmp_path,
            "pptx",
            {
                "__pycache__/cached.pyc": "junk",
                ".DS_Store": "junk",
                "scripts/.hidden": "junk",
            },
        )
        BuiltinSkillRegistry.instance().register(slug="pptx", source_dir=source)

        files = build_skills_fileset_for_user(test_user, db_session)

        assert set(files) == {"pptx/SKILL.md"}


class TestTemplateBuiltinFileset:
    def test_template_builtin_is_rendered_per_user(
        self,
        tmp_path: Path,
        db_session: Session,
        test_user: User,
    ) -> None:
        # The company-search template contains a {{AVAILABLE_SOURCES_SECTION}}
        # marker that the renderer substitutes with the user's cc-pair sources.
        template_body = (
            f"{_FRONTMATTER.format(slug='company-search')}"
            "Sources:\n{{AVAILABLE_SOURCES_SECTION}}\n"
        )
        source = _write_template_builtin(
            tmp_path, "company-search", template_body=template_body
        )
        BuiltinSkillRegistry.instance().register(
            slug="company-search", source_dir=source
        )
        make_cc_pair(db_session, DocumentSource.SLACK)

        files = build_skills_fileset_for_user(test_user, db_session)

        rendered = files["company-search/SKILL.md"].decode("utf-8")
        # The marker is substituted, not shipped raw.
        assert "{{AVAILABLE_SOURCES_SECTION}}" not in rendered
        # And the user's actual source shows up in the rendered body.
        assert "slack" in rendered

    def test_template_builtin_includes_static_siblings(
        self,
        tmp_path: Path,
        db_session: Session,
        test_user: User,
    ) -> None:
        template_body = (
            f"{_FRONTMATTER.format(slug='company-search')}"
            "{{AVAILABLE_SOURCES_SECTION}}\n"
        )
        source = _write_template_builtin(
            tmp_path,
            "company-search",
            template_body=template_body,
            extra_files={"scripts/search.py": "print('search')"},
        )
        BuiltinSkillRegistry.instance().register(
            slug="company-search", source_dir=source
        )
        make_cc_pair(db_session, DocumentSource.GOOGLE_DRIVE)

        files = build_skills_fileset_for_user(test_user, db_session)

        # Rendered SKILL.md AND static sibling are both present.
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
        # ``team``; the bundle holds two files.
        team_group: UserGroup = make_group(db_session)
        add_user_to_group(db_session, test_user, team_group)
        db_session.commit()

        seeded_skill(
            slug="my-custom",
            public=False,
            groups=[team_group],
            bundle_files={
                "SKILL.md": "---\nname: my-custom\ndescription: c\n---\ncustom body",
                "nested/file.txt": "nested body",
            },
        )

        files = build_skills_fileset_for_user(test_user, db_session)

        assert b"custom body" in files["my-custom/SKILL.md"]
        assert files["my-custom/nested/file.txt"] == b"nested body"
