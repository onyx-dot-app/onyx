"""Unit tests for parse_skill_source — no services required."""

from __future__ import annotations

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.skills.marketplace import parse_skill_source
from onyx.skills.marketplace import ParsedSource


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Full npx skills add command with --skill filter
        (
            "npx skills add https://github.com/vercel-labs/skills --skill find-skills",
            ParsedSource(
                host="github.com",
                owner="vercel-labs",
                repo="skills",
                ref=None,
                subpath=None,
                skill_filters=["find-skills"],
            ),
        ),
        # skills add with two --skill flags
        (
            "skills add owner/repo --skill a --skill b",
            ParsedSource(
                host="github.com",
                owner="owner",
                repo="repo",
                ref=None,
                subpath=None,
                skill_filters=["a", "b"],
            ),
        ),
        # Bare owner/repo — defaults to github.com, no ref/subpath
        (
            "owner/repo",
            ParsedSource(
                host="github.com",
                owner="owner",
                repo="repo",
                ref=None,
                subpath=None,
                skill_filters=[],
            ),
        ),
        # .git suffix stripped
        (
            "https://github.com/o/r.git",
            ParsedSource(
                host="github.com",
                owner="o",
                repo="r",
                ref=None,
                subpath=None,
                skill_filters=[],
            ),
        ),
        # /tree/<ref>/<subpath> parsed
        (
            "https://github.com/o/r/tree/main/skills/x",
            ParsedSource(
                host="github.com",
                owner="o",
                repo="r",
                ref="main",
                subpath="skills/x",
                skill_filters=[],
            ),
        ),
        # gitlab.com host accepted
        (
            "https://gitlab.com/o/r",
            ParsedSource(
                host="gitlab.com",
                owner="o",
                repo="r",
                ref=None,
                subpath=None,
                skill_filters=[],
            ),
        ),
        # GitLab /-/tree/<ref>/<subpath> — the "-" separator is handled
        (
            "https://gitlab.com/o/r/-/tree/main/skills/foo",
            ParsedSource(
                host="gitlab.com",
                owner="o",
                repo="r",
                ref="main",
                subpath="skills/foo",
                skill_filters=[],
            ),
        ),
        # GitLab subgroups: the project path before "-" may be nested, so the
        # owner namespace keeps every segment except the final repo name.
        (
            "https://gitlab.com/group/subgroup/r/-/tree/main/skills/foo",
            ParsedSource(
                host="gitlab.com",
                owner="group/subgroup",
                repo="r",
                ref="main",
                subpath="skills/foo",
                skill_filters=[],
            ),
        ),
        (
            "https://gitlab.com/group/sub1/sub2/r/-/tree/dev",
            ParsedSource(
                host="gitlab.com",
                owner="group/sub1/sub2",
                repo="r",
                ref="dev",
                subpath=None,
                skill_filters=[],
            ),
        ),
    ],
)
def test_parse_skill_source_ok(raw: str, expected: ParsedSource) -> None:
    assert parse_skill_source(raw) == expected


def test_unsupported_host_raises() -> None:
    with pytest.raises(OnyxError):
        parse_skill_source("https://evil.com/o/r")


def test_garbage_string_raises() -> None:
    with pytest.raises(OnyxError):
        parse_skill_source("notavalidsource")


def test_bare_hostname_only_raises() -> None:
    # e.g. "github.com/owner" — only one path segment after host
    with pytest.raises(OnyxError):
        parse_skill_source("github.com/onlyowner")


def test_tree_url_without_ref_raises() -> None:
    # /owner/repo/tree/ with nothing after
    with pytest.raises(OnyxError):
        parse_skill_source("https://github.com/o/r/tree/")


def test_ref_only_no_subpath() -> None:
    result = parse_skill_source("https://github.com/o/r/tree/main")
    assert result.ref == "main"
    assert result.subpath is None


def test_skill_filters_deduplication_not_done_by_parser() -> None:
    # Parser does NOT deduplicate — it just collects all --skill values.
    result = parse_skill_source("skills add owner/repo --skill a --skill a")
    assert result.skill_filters == ["a", "a"]


def test_git_suffix_stripped_in_bare_form() -> None:
    result = parse_skill_source("owner/repo.git")
    assert result.repo == "repo"
