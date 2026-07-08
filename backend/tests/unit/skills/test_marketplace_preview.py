"""Unit tests for _preview_repo_skills — no services required."""

from __future__ import annotations

import io
import tarfile

import pytest

from onyx.server.features.skill.api import _preview_repo_skills


def _make_tar(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            b = data.encode()
            ti = tarfile.TarInfo(name)
            ti.size = len(b)
            ti.mtime = 0
            tf.addfile(ti, io.BytesIO(b))
    return buf.getvalue()


def _skill_md(name: str, description: str = "does things") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n# body\n"


class TestPreviewRepoSkills:
    def test_skill_filter_marks_matching_slug_preselected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A source with --skill <slug> → only that skill has pre_selected=True."""
        archive = _make_tar(
            {
                "repo-main/skills/alpha/SKILL.md": _skill_md("Alpha"),
                "repo-main/skills/beta/SKILL.md": _skill_md("Beta"),
            }
        )
        monkeypatch.setattr(
            "onyx.server.features.skill.api.fetch_repo_archive",
            lambda _parsed: archive,
        )

        preview = _preview_repo_skills("skills add owner/repo --skill alpha")

        slugs = {item.slug: item.pre_selected for item in preview.skills}
        assert slugs.get("alpha") is True
        assert slugs.get("beta") is False

    def test_no_filter_all_preselected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No --skill filter → all preview items have pre_selected=True."""
        archive = _make_tar(
            {
                "repo-main/skills/alpha/SKILL.md": _skill_md("Alpha"),
                "repo-main/skills/beta/SKILL.md": _skill_md("Beta"),
            }
        )
        monkeypatch.setattr(
            "onyx.server.features.skill.api.fetch_repo_archive",
            lambda _parsed: archive,
        )

        preview = _preview_repo_skills("owner/repo")

        assert all(item.pre_selected for item in preview.skills)
        assert len(preview.skills) == 2
