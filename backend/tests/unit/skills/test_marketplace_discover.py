"""Unit tests for extracted_skills and build_bundle_for_skill — no services required."""

from __future__ import annotations

import io
import tarfile
import zipfile

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.skills.bundle import validate_custom_bundle
from onyx.skills.marketplace import build_bundle_for_skill
from onyx.skills.marketplace import extracted_skills

_VALID_SKILL_MD = "---\nname: My Skill\ndescription: does things\n---\n# body\n"


def make_tar(files: dict[str, str]) -> bytes:
    """Build a GitHub-style tar.gz with a single top-level wrapper dir."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            b = data.encode()
            ti = tarfile.TarInfo(name)
            ti.size = len(b)
            ti.mtime = 0
            tf.addfile(ti, io.BytesIO(b))
    return buf.getvalue()


def make_tar_bytes(files: dict[str, bytes]) -> bytes:
    """Like make_tar but accepts raw bytes values."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mtime = 0
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def test_flat_skill_discovered() -> None:
    archive = make_tar({"repo-main/skills/my-tool/SKILL.md": _VALID_SKILL_MD})
    with extracted_skills(archive) as skills:
        slugs = [s.slug for s in skills]
    assert "my-tool" in slugs


def test_subpath_pointing_at_skill_dir_uses_dir_slug() -> None:
    # A tree/subpath URL pointing directly at a skill dir must derive the slug
    # from that dir (e.g. "docx"), not the repo wrapper name.
    archive = make_tar({"repo-main/skills/docx/SKILL.md": _VALID_SKILL_MD})
    with extracted_skills(archive, subpath="skills/docx") as skills:
        slugs = [s.slug for s in skills]
    assert slugs == ["docx"]


def test_catalog_skill_discovered() -> None:
    # skills/cat/deep/SKILL.md  — two levels under skills/
    archive = make_tar({"repo-main/skills/cat/deep/SKILL.md": _VALID_SKILL_MD})
    with extracted_skills(archive) as skills:
        slugs = [s.slug for s in skills]
    assert "deep" in slugs


def test_claude_skills_discovered() -> None:
    archive = make_tar({"repo-main/.claude/skills/cl/SKILL.md": _VALID_SKILL_MD})
    with extracted_skills(archive) as skills:
        slugs = [s.slug for s in skills]
    assert "cl" in slugs


def test_root_level_skill_discovered() -> None:
    archive = make_tar({"repo-main/SKILL.md": _VALID_SKILL_MD})
    with extracted_skills(archive) as skills:
        assert len(skills) == 1
        # slug comes from repo dir name "repo-main" → strips "-main" → "repo"
        assert skills[0].slug == "repo"


def test_multiple_layout_archive() -> None:
    archive = make_tar(
        {
            "repo-main/skills/flat/SKILL.md": _VALID_SKILL_MD,
            "repo-main/skills/cat/deep/SKILL.md": _VALID_SKILL_MD,
            "repo-main/.claude/skills/cl/SKILL.md": _VALID_SKILL_MD,
        }
    )
    with extracted_skills(archive) as skills:
        slugs = {s.slug for s in skills}
    assert "flat" in slugs
    assert "deep" in slugs
    assert "cl" in slugs


def test_name_and_description_from_frontmatter() -> None:
    skill_md = "---\nname: Fancy Tool\ndescription: Does fancy things\n---\n"
    archive = make_tar({"repo-main/skills/fancy-tool/SKILL.md": skill_md})
    with extracted_skills(archive) as skills:
        assert len(skills) == 1
        assert skills[0].name == "Fancy Tool"
        assert skills[0].description == "Does fancy things"


def test_build_bundle_passes_validate() -> None:
    archive = make_tar(
        {
            "repo-main/skills/my-tool/SKILL.md": _VALID_SKILL_MD,
            "repo-main/skills/my-tool/helper.py": "print('hi')\n",
        }
    )
    with extracted_skills(archive) as skills:
        assert len(skills) == 1
        bundle = build_bundle_for_skill(skills[0])
    validate_custom_bundle(bundle, slug=skills[0].slug)


def test_build_bundle_includes_sibling_file() -> None:
    archive = make_tar(
        {
            "repo-main/skills/my-tool/SKILL.md": _VALID_SKILL_MD,
            "repo-main/skills/my-tool/helper.py": "print('hi')\n",
        }
    )
    with extracted_skills(archive) as skills:
        assert len(skills) == 1
        bundle = build_bundle_for_skill(skills[0])

    zf = zipfile.ZipFile(io.BytesIO(bundle))
    names = zf.namelist()
    assert "SKILL.md" in names
    assert "helper.py" in names


def test_subpath_filters_skills() -> None:
    # With subpath="skills/inner", search_root = repo-main/skills/inner.
    # The flat pattern skills/*/SKILL.md becomes skills/inner/skills/tool/SKILL.md
    # which is deep. Easier: put a skill directly at root of the subpath tree.
    # subpath="skills/in-scope" → search_root = repo-main/skills/in-scope
    # → _add(search_root) picks up SKILL.md there; slug = dir name with -main stripped.
    archive = make_tar(
        {
            "repo-main/skills/in-scope/SKILL.md": _VALID_SKILL_MD,
            # This skill is outside the subpath — should NOT appear
            "repo-main/.claude/skills/outside/SKILL.md": _VALID_SKILL_MD,
        }
    )
    with extracted_skills(archive, subpath="skills/in-scope") as skills:
        slugs = {s.slug for s in skills}
    # Exactly one skill found — the one inside the subpath. A subpath leaf keeps
    # its own dir name as the slug (only a true repo-root SKILL.md falls back to
    # the repo wrapper name), so the slug is "in-scope", not "repo".
    assert slugs == {"in-scope"}
    assert "outside" not in slugs


def test_subpath_not_found_raises() -> None:
    archive = make_tar({"repo-main/skills/tool/SKILL.md": _VALID_SKILL_MD})
    with pytest.raises(OnyxError):
        with extracted_skills(archive, subpath="nonexistent") as _:
            pass


def test_tar_traversal_raises() -> None:
    # "../../evil.txt" resolves to a path above dest, triggering the OnyxError.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        evil_data = b"evil"
        ti = tarfile.TarInfo("../../evil.txt")
        ti.size = len(evil_data)
        ti.mtime = 0
        tf.addfile(ti, io.BytesIO(evil_data))
    archive = buf.getvalue()

    with pytest.raises(OnyxError):
        with extracted_skills(archive) as _:
            pass


def test_invalid_skill_md_skipped() -> None:
    # SKILL.md with no frontmatter — parser raises OnyxError → skill is skipped.
    bad_skill_md = "# No frontmatter here\nJust body text.\n"
    good_skill_md = _VALID_SKILL_MD
    archive = make_tar(
        {
            "repo-main/skills/bad-skill/SKILL.md": bad_skill_md,
            "repo-main/skills/good-skill/SKILL.md": good_skill_md,
        }
    )
    with extracted_skills(archive) as skills:
        slugs = {s.slug for s in skills}
    assert "bad-skill" not in slugs
    assert "good-skill" in slugs


def test_invalid_skill_md_only_no_crash() -> None:
    bad_skill_md = "# No frontmatter\n"
    archive = make_tar({"repo-main/skills/bad/SKILL.md": bad_skill_md})
    with extracted_skills(archive) as skills:
        assert skills == []


def _tar_with_special_member(member_type: bytes, name: str = "repo-main/evil") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        ti = tarfile.TarInfo(name)
        ti.type = member_type
        if member_type in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            ti.linkname = "/etc/passwd"
        ti.size = 0
        ti.mtime = 0
        tf.addfile(ti)
    return buf.getvalue()


def test_tar_symlink_rejected() -> None:
    # A symlink member could point anywhere on the host — extraction must refuse.
    archive = _tar_with_special_member(tarfile.SYMTYPE)
    with pytest.raises(OnyxError):
        with extracted_skills(archive) as _:
            pass


def test_tar_hardlink_rejected() -> None:
    archive = _tar_with_special_member(tarfile.LNKTYPE)
    with pytest.raises(OnyxError):
        with extracted_skills(archive) as _:
            pass


def test_tar_non_regular_member_rejected() -> None:
    # Device/FIFO members are neither file nor dir — must be refused.
    archive = _tar_with_special_member(tarfile.FIFOTYPE)
    with pytest.raises(OnyxError):
        with extracted_skills(archive) as _:
            pass


def test_per_file_size_cap_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("onyx.skills.marketplace.DEFAULT_PER_FILE_MAX_BYTES", 8)
    archive = make_tar_bytes({"repo-main/skills/big/SKILL.md": b"x" * 64})
    with pytest.raises(OnyxError):
        with extracted_skills(archive) as _:
            pass


def test_total_size_cap_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("onyx.skills.marketplace.DEFAULT_PER_FILE_MAX_BYTES", 1024)
    monkeypatch.setattr("onyx.skills.marketplace.DEFAULT_TOTAL_MAX_BYTES", 16)
    archive = make_tar_bytes(
        {
            "repo-main/skills/a/SKILL.md": b"x" * 12,
            "repo-main/skills/b/SKILL.md": b"y" * 12,
        }
    )
    with pytest.raises(OnyxError):
        with extracted_skills(archive) as _:
            pass


def test_member_count_cap_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("onyx.skills.marketplace._TAR_MAX_MEMBERS", 2)
    archive = make_tar(
        {
            "repo-main/a.txt": "a",
            "repo-main/b.txt": "b",
            "repo-main/c.txt": "c",
        }
    )
    with pytest.raises(OnyxError):
        with extracted_skills(archive) as _:
            pass


def test_manifest_declared_skill_discovered() -> None:
    # .claude-plugin/marketplace.json "skills" array points at a dir whose name
    # need not match any of the auto-scanned layouts.
    archive = make_tar(
        {
            "repo-main/.claude-plugin/marketplace.json": '{"skills": ["tools/widget"]}',
            "repo-main/tools/widget/SKILL.md": _VALID_SKILL_MD,
        }
    )
    with extracted_skills(archive) as skills:
        slugs = {s.slug for s in skills}
    assert "widget" in slugs


def test_manifest_path_confinement() -> None:
    # An escaping manifest entry is ignored (untrusted archive content); the
    # confined sibling entry is still discovered.
    archive = make_tar(
        {
            "repo-main/.claude-plugin/marketplace.json": (
                '{"skills": ["nested/ok", "../escape", "/etc"]}'
            ),
            "repo-main/nested/ok/SKILL.md": _VALID_SKILL_MD,
        }
    )
    with extracted_skills(archive) as skills:
        slugs = {s.slug for s in skills}
    assert "ok" in slugs
    assert "escape" not in slugs


def test_subpath_traversal_escape_raises() -> None:
    archive = make_tar({"repo-main/skills/tool/SKILL.md": _VALID_SKILL_MD})
    with pytest.raises(OnyxError, match="escapes repository root"):
        with extracted_skills(archive, subpath="../../etc") as _:
            pass


def test_manifest_plugins_format_discovered() -> None:
    archive = make_tar(
        {
            "repo-main/.claude-plugin/plugin.json": (
                '{"plugins": [{"metadata": {"pluginRoot": "pkg"}, '
                '"skills": ["widget"]}]}'
            ),
            "repo-main/pkg/widget/SKILL.md": _VALID_SKILL_MD,
        }
    )
    with extracted_skills(archive) as skills:
        slugs = {s.slug for s in skills}
    assert "widget" in slugs


def test_manifest_plugins_escaping_plugin_root_skipped() -> None:
    archive = make_tar(
        {
            "repo-main/.claude-plugin/marketplace.json": (
                '{"plugins": ['
                '{"metadata": {"pluginRoot": "../evil"}, "skills": ["x"]}, '
                '{"metadata": {"pluginRoot": "pkg"}, "skills": ["widget"]}'
                "]}"
            ),
            "repo-main/pkg/widget/SKILL.md": _VALID_SKILL_MD,
        }
    )
    with extracted_skills(archive) as skills:
        slugs = {s.slug for s in skills}
    assert "widget" in slugs
    assert "x" not in slugs


def test_build_bundle_per_file_cap_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    # Extract at the real cap, then lower it for the build — moving the
    # monkeypatch before extraction would trip the extraction-time cap instead.
    archive = make_tar(
        {
            "repo-main/skills/my-tool/SKILL.md": _VALID_SKILL_MD,
            "repo-main/skills/my-tool/big.bin": "x" * 256,
        }
    )
    with extracted_skills(archive) as skills:
        assert len(skills) == 1
        monkeypatch.setattr("onyx.skills.marketplace.DEFAULT_PER_FILE_MAX_BYTES", 16)
        with pytest.raises(OnyxError):
            build_bundle_for_skill(skills[0])


def test_agents_skills_layout_discovered() -> None:
    archive = make_tar({"repo-main/.agents/skills/ag/SKILL.md": _VALID_SKILL_MD})
    with extracted_skills(archive) as skills:
        slugs = {s.slug for s in skills}
    assert "ag" in slugs


def test_curated_container_discovered() -> None:
    archive = make_tar({"repo-main/skills/.curated/cur/SKILL.md": _VALID_SKILL_MD})
    with extracted_skills(archive) as skills:
        slugs = {s.slug for s in skills}
    assert "cur" in slugs


def test_non_sluggable_dir_name_skipped() -> None:
    archive = make_tar(
        {
            "repo-main/skills/!!!/SKILL.md": _VALID_SKILL_MD,
            "repo-main/skills/good/SKILL.md": _VALID_SKILL_MD,
        }
    )
    with extracted_skills(archive) as skills:
        slugs = {s.slug for s in skills}
    assert slugs == {"good"}


def test_build_bundle_excludes_template_and_pycache() -> None:
    archive = make_tar(
        {
            "repo-main/skills/my-tool/SKILL.md": _VALID_SKILL_MD,
            "repo-main/skills/my-tool/keep.py": "print('hi')\n",
            "repo-main/skills/my-tool/SKILL.md.template": "ignored\n",
            "repo-main/skills/my-tool/__pycache__/x.pyc": "bytecode\n",
        }
    )
    with extracted_skills(archive) as skills:
        assert len(skills) == 1
        bundle = build_bundle_for_skill(skills[0])

    names = zipfile.ZipFile(io.BytesIO(bundle)).namelist()
    assert "SKILL.md" in names
    assert "keep.py" in names
    assert "SKILL.md.template" not in names
    assert not any("__pycache__" in n for n in names)
