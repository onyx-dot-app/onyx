"""Unit tests for the GitLab connector's incremental (diff-based) code-file logic
and its glob-based file filtering.

These exercise the local-git diff computation against a throwaway repository, so
they only depend on a local ``git`` binary (no GitLab API / Onyx services).
"""

from datetime import datetime, timezone
from pathlib import Path

import git
import pytest

from onyx.connectors.gitlab.connector import (
    DEFAULT_CODE_FILE_PATTERNS,
    GitlabConnector,
    _matches_glob,
    _normalize_patterns,
)


def _commit_file(
    repo: git.Repo, repo_path: Path, rel_path: str, content: str, when: datetime
) -> None:
    file_path = repo_path / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)
    repo.index.add([rel_path])
    date_str = when.strftime("%Y-%m-%dT%H:%M:%S")
    repo.index.commit(
        f"add {rel_path}",
        author_date=date_str,
        commit_date=date_str,
    )


@pytest.fixture
def gitlab_connector() -> GitlabConnector:
    # No credentials needed: the diff/filter methods only use repo_path/git_repo.
    return GitlabConnector(
        project_owner="owner",
        project_name="repo",
        include_code_files=True,
    )


@pytest.fixture
def local_repo(tmp_path: Path) -> tuple[git.Repo, Path]:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repo = git.Repo.init(repo_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")

    # An extensionless code file (no Path.suffix) — only matched by globs.
    _commit_file(
        repo, repo_path, "Makefile", "all:\n\techo hi", datetime(2020, 1, 1, 10, 0, 0)
    )
    _commit_file(
        repo, repo_path, "old.py", "print('old')", datetime(2020, 1, 1, 12, 0, 0)
    )
    _commit_file(
        repo, repo_path, "new.py", "print('new')", datetime(2024, 6, 1, 12, 0, 0)
    )
    _commit_file(
        repo, repo_path, "data.bin", "not-code", datetime(2024, 6, 2, 12, 0, 0)
    )
    return repo, repo_path


def test_normalize_patterns_strips_dedups_and_migrates_legacy() -> None:
    # Whitespace stripped, empties + duplicates dropped, order preserved, and the
    # legacy regex "match all" (".*") rewritten to its glob equivalent ("*").
    assert _normalize_patterns([" *.py ", "*.py", "", "Makefile", ".*"]) == [
        "*.py",
        "Makefile",
        "*",
    ]


def test_matches_glob_basename_vs_path() -> None:
    # No-slash patterns match the basename anywhere in the tree.
    assert _matches_glob("src/a/b/foo.py", "*.py")
    assert _matches_glob("Makefile", "Makefile")
    assert _matches_glob("build/Makefile", "Makefile")
    # Slash patterns match against the full relative path.
    assert _matches_glob("src/foo.py", "src/*.py")
    assert not _matches_glob("lib/foo.py", "src/*.py")


def test_default_patterns_used_when_unset() -> None:
    connector = GitlabConnector(project_owner="o", project_name="n")
    assert connector.code_file_patterns == list(DEFAULT_CODE_FILE_PATTERNS)
    # Makefile / Dockerfile are extensionless but covered by the defaults.
    assert "Makefile" in connector.code_file_patterns
    assert "Dockerfile" in connector.code_file_patterns


def test_custom_patterns_override_defaults() -> None:
    connector = GitlabConnector(
        project_owner="o", project_name="n", code_file_patterns=["*.go", "Dockerfile"]
    )
    assert connector.code_file_patterns == ["*.go", "Dockerfile"]


def test_legacy_code_file_extensions_converted_to_globs() -> None:
    # Connectors created before the glob migration store bare extensions; the
    # deprecated kwarg must still be accepted (no TypeError) and converted.
    connector = GitlabConnector(
        project_owner="o", project_name="n", code_file_extensions=[".py", "ts"]
    )
    assert connector.code_file_patterns == ["*.py", "*.ts"]


def test_changed_paths_since_returns_only_recent_changes(
    gitlab_connector: GitlabConnector, local_repo: tuple[git.Repo, Path]
) -> None:
    repo, repo_path = local_repo
    gitlab_connector.git_repo = repo
    gitlab_connector.repo_path = repo_path

    # A window starting in 2022 should only pick up the 2024 commits.
    start = datetime(2022, 1, 1, tzinfo=timezone.utc)
    changed = gitlab_connector._get_changed_paths_since(start)

    assert changed == {"new.py", "data.bin"}


def test_changed_paths_since_full_index_when_no_prior_commit(
    gitlab_connector: GitlabConnector, local_repo: tuple[git.Repo, Path]
) -> None:
    repo, repo_path = local_repo
    gitlab_connector.git_repo = repo
    gitlab_connector.repo_path = repo_path

    # The window predates the whole repo history -> signal a full index (None).
    start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    assert gitlab_connector._get_changed_paths_since(start) is None


def test_changed_paths_since_empty_when_nothing_changed(
    gitlab_connector: GitlabConnector, local_repo: tuple[git.Repo, Path]
) -> None:
    repo, repo_path = local_repo
    gitlab_connector.git_repo = repo
    gitlab_connector.repo_path = repo_path

    # A window after the last commit -> no changes to re-index.
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert gitlab_connector._get_changed_paths_since(start) == set()


def test_get_filtered_files_matches_extensionless_code_files(
    gitlab_connector: GitlabConnector, local_repo: tuple[git.Repo, Path]
) -> None:
    _, repo_path = local_repo
    gitlab_connector.repo_path = repo_path

    # Makefile (no extension) is now indexed via glob; data.bin is not a code file.
    filtered = sorted(
        p.name
        for p in gitlab_connector._get_filtered_files(
            {"new.py", "data.bin", "Makefile"}
        )
    )
    assert filtered == ["Makefile", "new.py"]


def test_get_filtered_files_full_scan_indexes_all_code_files(
    gitlab_connector: GitlabConnector, local_repo: tuple[git.Repo, Path]
) -> None:
    _, repo_path = local_repo
    gitlab_connector.repo_path = repo_path

    filtered = sorted(p.name for p in gitlab_connector._get_filtered_files(None))
    assert filtered == ["Makefile", "new.py", "old.py"]


def test_exclude_glob_patterns_take_effect(local_repo: tuple[git.Repo, Path]) -> None:
    _, repo_path = local_repo
    connector = GitlabConnector(
        project_owner="o",
        project_name="n",
        include_code_files=True,
        exclude_path_patterns=["*.py"],
    )
    connector.repo_path = repo_path

    # Excluding *.py leaves only the Makefile from the code files.
    filtered = sorted(p.name for p in connector._get_filtered_files(None))
    assert filtered == ["Makefile"]
