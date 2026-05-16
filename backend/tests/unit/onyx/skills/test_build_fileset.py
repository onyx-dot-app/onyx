"""Unit tests for ``build_skills_fileset_for_user``."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from onyx.skills import push as push_module
from onyx.skills.push import build_skills_fileset_for_user
from onyx.skills.registry import BuiltinSkillRegistry

_FRONTMATTER = "---\nname: {slug}\ndescription: {slug}\n---\n"


def _make_static_builtin(tmp_path: Path, slug: str, files: dict[str, str]) -> Path:
    source_dir = tmp_path / slug
    source_dir.mkdir(parents=True)
    (source_dir / "SKILL.md").write_text(
        _FRONTMATTER.format(slug=slug), encoding="utf-8"
    )
    for rel, content in files.items():
        path = source_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return source_dir


def test_static_builtin_files_are_included_under_slug_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    BuiltinSkillRegistry._reset_for_testing()
    source = _make_static_builtin(
        tmp_path, "pptx", {"scripts/preview.py": "print('hi')"}
    )
    BuiltinSkillRegistry.instance().register(slug="pptx", source_dir=source)

    monkeypatch.setattr(push_module, "list_skills_for_user", lambda *_, **__: [])

    user = MagicMock()
    files = build_skills_fileset_for_user(user, db_session=MagicMock())

    assert b"name: pptx" in files["pptx/SKILL.md"]
    assert files["pptx/scripts/preview.py"] == b"print('hi')"


def test_excluded_dirs_and_dotfiles_are_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    BuiltinSkillRegistry._reset_for_testing()
    source = _make_static_builtin(
        tmp_path,
        "pptx",
        {
            "__pycache__/cached.pyc": "junk",
            ".DS_Store": "junk",
            "scripts/.hidden": "junk",
        },
    )
    BuiltinSkillRegistry.instance().register(slug="pptx", source_dir=source)
    monkeypatch.setattr(push_module, "list_skills_for_user", lambda *_, **__: [])

    files = build_skills_fileset_for_user(MagicMock(), db_session=MagicMock())

    assert set(files) == {"pptx/SKILL.md"}


def test_template_builtin_is_rendered_per_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    BuiltinSkillRegistry._reset_for_testing()

    source_dir = tmp_path / "company-search"
    source_dir.mkdir()
    (source_dir / "SKILL.md.template").write_text(
        _FRONTMATTER.format(slug="company-search"), encoding="utf-8"
    )
    BuiltinSkillRegistry.instance().register(
        slug="company-search", source_dir=source_dir
    )
    registered = BuiltinSkillRegistry.instance().get("company-search")
    assert registered is not None and registered.has_template

    rendered_calls: list[tuple[object, object, Path]] = []

    def fake_render(db_session: object, user: object, skills_dir: Path) -> str:
        rendered_calls.append((db_session, user, skills_dir))
        return "RENDERED"

    monkeypatch.setattr(push_module, "render_company_search_skill", fake_render)
    monkeypatch.setattr(push_module, "list_skills_for_user", lambda *_, **__: [])

    db_session = MagicMock()
    user = MagicMock()
    files = build_skills_fileset_for_user(user, db_session=db_session)

    assert files["company-search/SKILL.md"] == b"RENDERED"
    assert len(rendered_calls) == 1
    called_db, called_user, called_dir = rendered_calls[0]
    assert called_db is db_session
    assert called_user is user
    assert called_dir == source_dir.parent


def test_template_builtin_includes_static_siblings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    BuiltinSkillRegistry._reset_for_testing()

    source_dir = tmp_path / "company-search"
    source_dir.mkdir()
    (source_dir / "SKILL.md.template").write_text(
        _FRONTMATTER.format(slug="company-search"), encoding="utf-8"
    )
    (source_dir / "scripts").mkdir()
    (source_dir / "scripts" / "search.py").write_text(
        "print('search')", encoding="utf-8"
    )

    BuiltinSkillRegistry.instance().register(
        slug="company-search", source_dir=source_dir
    )

    monkeypatch.setattr(
        push_module, "render_company_search_skill", lambda *_, **__: "RENDERED"
    )
    monkeypatch.setattr(push_module, "list_skills_for_user", lambda *_, **__: [])

    files = build_skills_fileset_for_user(MagicMock(), db_session=MagicMock())

    assert files["company-search/SKILL.md"] == b"RENDERED"
    assert files["company-search/scripts/search.py"] == b"print('search')"
    assert "company-search/SKILL.md.template" not in files


def test_custom_bundle_entries_are_added_under_their_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io
    import zipfile

    BuiltinSkillRegistry._reset_for_testing()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("SKILL.md", "custom body")
        zf.writestr("nested/file.txt", "nested body")
    bundle_bytes = buf.getvalue()

    custom = MagicMock()
    custom.slug = "my-custom"
    custom.bundle_file_id = "file-id"
    monkeypatch.setattr(push_module, "list_skills_for_user", lambda *_, **__: [custom])

    class _Blob:
        def read(self) -> bytes:
            return bundle_bytes

    file_store = MagicMock()
    file_store.read_file.return_value = _Blob()
    monkeypatch.setattr(push_module, "get_default_file_store", lambda: file_store)

    files = build_skills_fileset_for_user(MagicMock(), db_session=MagicMock())

    assert files["my-custom/SKILL.md"] == b"custom body"
    assert files["my-custom/nested/file.txt"] == b"nested body"
