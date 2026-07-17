import io
import tarfile
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import BinaryIO
from typing import cast
from unittest.mock import MagicMock

import pytest

import onyx.connectors.gitlab.connector as gitlab_connector_module
from onyx.connectors.gitlab.connector import _archive_relative_path
from onyx.connectors.gitlab.connector import _build_file_id
from onyx.connectors.gitlab.connector import _build_file_link
from onyx.connectors.gitlab.connector import _is_default_excluded
from onyx.connectors.gitlab.connector import _matches_glob
from onyx.connectors.gitlab.connector import _normalize_patterns
from onyx.connectors.gitlab.connector import GitlabConnector
from onyx.connectors.gitlab.connector import GitlabConnectorCheckpoint
from onyx.connectors.gitlab.connector import GitlabObjectType
from onyx.connectors.gitlab.connector import GitlabSyncStage
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document


def _connector(
    *,
    include_path_patterns: list[str] | None = None,
    exclude_path_patterns: list[str] | None = None,
    code_file_patterns: list[str] | None = None,
    code_file_extensions: list[str] | None = None,
) -> GitlabConnector:
    return GitlabConnector(
        project_owner="owner",
        project_name="repo",
        include_mrs=False,
        include_issues=False,
        include_code_files=True,
        include_path_patterns=include_path_patterns,
        exclude_path_patterns=exclude_path_patterns,
        code_file_patterns=code_file_patterns,
        code_file_extensions=code_file_extensions,
    )


def _tar_bytes(
    files: dict[str, bytes],
    symlinks: dict[str, str] | None = None,
) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for path, content in files.items():
            member = tarfile.TarInfo(f"repo-sha/{path}")
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
        for path, target in (symlinks or {}).items():
            member = tarfile.TarInfo(f"repo-sha/{path}")
            member.type = tarfile.SYMTYPE
            member.linkname = target
            archive.addfile(member)
    return output.getvalue()


def _use_archive(
    monkeypatch: pytest.MonkeyPatch,
    connector: GitlabConnector,
    content: bytes,
) -> None:
    @contextmanager
    def archive_context(*_: object) -> Iterator[BinaryIO]:
        yield io.BytesIO(content)

    monkeypatch.setattr(connector, "_download_archive", archive_context)


def test_normalize_patterns_strips_deduplicates_and_migrates_legacy() -> None:
    assert _normalize_patterns([" *.py ", "", "*.py", "src\\**", "Makefile"]) == [
        "*.py",
        "src/**",
        "Makefile",
    ]
    assert _connector(code_file_extensions=[".py", "js"]).code_file_patterns == [
        "*.py",
        "*.js",
    ]


@pytest.mark.parametrize(
    ("path", "pattern", "matches"),
    [
        ("main.py", "*.py", True),
        ("src/main.py", "*.py", True),
        ("src/main.py", "src/*.py", True),
        ("src/nested/main.py", "src/*.py", False),
        ("src/nested/main.py", "src/**/*.py", True),
        ("nested/src/main.py", "src/*.py", False),
        ("Makefile", "Makefile", True),
    ],
)
def test_glob_semantics(path: str, pattern: str, matches: bool) -> None:
    assert _matches_glob(path, pattern) is matches


@pytest.mark.parametrize(
    "path",
    [
        "node_modules/package/index.js",
        "frontend/node_modules/package/index.js",
        ".github/workflows/test.yml",
        "src/__pycache__/module.pyc",
    ],
)
def test_default_exclusions_match_nested_directories(path: str) -> None:
    assert _is_default_excluded(path)


def test_archive_path_normalization_rejects_unsafe_paths() -> None:
    assert _archive_relative_path("repo-sha/src/main.py") == "src/main.py"
    assert _archive_relative_path("repo-sha/src\\main.py") == "src\\main.py"
    assert _archive_relative_path("../secret") is None
    assert _archive_relative_path("/repo-sha/secret") is None


def test_file_urls_encode_reserved_characters() -> None:
    project_url = "https://gitlab.example/owner/repo"
    assert _build_file_link(project_url, "feature/a", "docs/a #?.md") == (
        "https://gitlab.example/owner/repo/-/blob/feature%2Fa/docs/a%20%23%3F.md"
    )
    assert _build_file_id(project_url, "feature/a", "docs/a #?.md") == (
        "https://gitlab.example/owner/repo/blob/feature%2Fa/docs/a%20%23%3F.md"
    )


def test_pattern_limits_are_validated() -> None:
    with pytest.raises(ValueError, match="more than"):
        _connector(include_path_patterns=[f"path-{index}" for index in range(201)])
    with pytest.raises(ValueError, match="cannot exceed"):
        _connector(exclude_path_patterns=["x" * 1_001])


def test_archive_sync_version_is_validated() -> None:
    with pytest.raises(ValueError, match="Unsupported GitLab archive sync version"):
        GitlabConnector(
            project_owner="owner",
            project_name="repo",
            archive_sync_version=0,
        )


def test_gitlab_client_uses_request_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_factory = MagicMock()
    monkeypatch.setattr(gitlab_connector_module.gitlab, "Gitlab", client_factory)

    _connector().load_credentials(
        {
            "gitlab_url": "https://gitlab.example/",
            "gitlab_access_token": "token",
        }
    )

    client_factory.assert_called_once_with(
        "https://gitlab.example",
        private_token="token",
        timeout=gitlab_connector_module.REQUEST_TIMEOUT_SECONDS,
        retry_transient_errors=True,
    )


def test_object_conversion_failure_preserves_document_id() -> None:
    connector = _connector()
    gitlab_object = SimpleNamespace(
        id=1,
        updated_at="2026-01-01T00:00:00Z",
        web_url="https://gitlab.example/owner/repo/-/issues/1",
    )

    def fail_conversion(_: object) -> Document:
        raise ValueError("invalid object")

    results = list(
        connector._iter_objects(
            objects=[gitlab_object],
            converter=fail_conversion,
            object_type=GitlabObjectType.ISSUE,
        )
    )

    assert len(results) == 1
    assert isinstance(results[0], ConnectorFailure)
    assert results[0].failed_document is not None
    assert results[0].failed_document.document_id == gitlab_object.web_url


def test_checkpoint_stages_code_merge_requests_and_issues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = GitlabConnector(
        project_owner="owner",
        project_name="repo",
        batch_size=2,
        include_code_files=False,
    )
    project = MagicMock(default_branch="main")
    monkeypatch.setattr(connector, "_get_project", lambda: project)
    project.mergerequests.list.return_value = [
        SimpleNamespace(id=1, updated_at="2026-01-01T00:00:00Z"),
        SimpleNamespace(id=2, updated_at="2026-01-01T00:00:00Z"),
        SimpleNamespace(id=3, updated_at="2026-01-01T00:00:00Z"),
    ]
    project.issues.list.return_value = []

    checkpoint = GitlabConnectorCheckpoint()
    expected_checkpoints = [
        (GitlabSyncStage.MERGE_REQUESTS, True),
        (GitlabSyncStage.ISSUES, True),
        (GitlabSyncStage.COMPLETE, False),
    ]
    for stage, has_more in expected_checkpoints:
        output = connector.load_from_checkpoint(
            start=0,
            end=1_800_000_000,
            checkpoint=checkpoint,
        )
        while True:
            try:
                next(output)
            except StopIteration as stop:
                checkpoint = stop.value
                break
        assert checkpoint.stage == stage
        assert checkpoint.has_more is has_more


def test_compare_returns_only_current_changed_paths() -> None:
    connector = _connector()
    project = MagicMock()
    project.commits.list.return_value = [SimpleNamespace(id="base")]
    project.repository_compare.return_value = {
        "compare_timeout": False,
        "diffs": [
            {"new_path": "src/updated.py", "deleted_file": False},
            {"new_path": "src/deleted.py", "deleted_file": True},
            {
                "old_path": "old.py",
                "new_path": "new.py",
                "deleted_file": False,
                "renamed_file": True,
            },
        ],
    }

    paths = connector._get_changed_paths(
        project,
        "main",
        gitlab_connector_module._FULL_INDEX_START_CUTOFF,
        "head",
    )

    assert paths == {"src/updated.py", "new.py"}
    project.repository_compare.assert_called_once_with(
        "base",
        "head",
        straight=True,
    )


def test_compare_skips_work_when_target_is_base() -> None:
    connector = _connector()
    project = MagicMock()
    project.commits.list.return_value = [SimpleNamespace(id="head")]

    assert (
        connector._get_changed_paths(
            project,
            "main",
            gitlab_connector_module._FULL_INDEX_START_CUTOFF,
            "head",
        )
        == set()
    )
    project.repository_compare.assert_not_called()


def test_compare_falls_back_when_base_is_missing_or_compare_times_out() -> None:
    connector = _connector()
    project = MagicMock()
    project.commits.list.return_value = []
    assert (
        connector._get_changed_paths(
            project,
            "main",
            gitlab_connector_module._FULL_INDEX_START_CUTOFF,
            "head",
        )
        is None
    )

    project.commits.list.return_value = [SimpleNamespace(id="base")]
    project.repository_compare.return_value = {"compare_timeout": True}
    assert (
        connector._get_changed_paths(
            project,
            "main",
            gitlab_connector_module._FULL_INDEX_START_CUTOFF,
            "head",
        )
        is None
    )


def test_archive_download_enforces_compressed_size_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _connector()
    project = MagicMock()
    monkeypatch.setattr(gitlab_connector_module, "MAX_ARCHIVE_SIZE_BYTES", 3)

    def repository_archive(**kwargs: object) -> None:
        action = cast(Callable[[bytes], None], kwargs["action"])
        action(b"four")

    project.repository_archive.side_effect = repository_archive
    with pytest.raises(ValueError, match="archive exceeds"):
        with connector._download_archive(project, "sha"):
            pass


def test_archive_enforces_file_count_and_content_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _connector(code_file_patterns=["*.py"])
    archive_bytes = _tar_bytes({"one.py": b"1", "two.py": b"22"})

    monkeypatch.setattr(gitlab_connector_module, "MAX_ARCHIVE_FILE_COUNT", 1)
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as archive:
        with pytest.raises(ValueError, match="exceeds 1 files"):
            list(connector._iter_archive_files(archive, None))

    monkeypatch.setattr(gitlab_connector_module, "MAX_ARCHIVE_FILE_COUNT", 100_000)
    monkeypatch.setattr(gitlab_connector_module, "MAX_ARCHIVE_CONTENT_SIZE_BYTES", 2)
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as archive:
        with pytest.raises(ValueError, match="extracted content exceeds"):
            list(connector._iter_archive_files(archive, None))


def test_archive_filters_files_and_ignores_symlinks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _connector(
        code_file_patterns=["*.py"],
        include_path_patterns=["src/**"],
        exclude_path_patterns=["**/*_test.py"],
    )
    archive_bytes = _tar_bytes(
        {
            "src/main.py": b"print('safe')",
            "src/main_test.py": b"assert True",
            "src/node_modules/package.py": b"vendored = True",
            "docs/readme.md": b"ignored",
        },
        symlinks={"src/secret.py": "/etc/passwd"},
    )
    _use_archive(monkeypatch, connector, archive_bytes)
    project = MagicMock(web_url="https://gitlab.example/owner/repo")

    results = list(connector._fetch_code_files(project, "main", "sha", None))

    documents = [result for result in results if isinstance(result, Document)]
    assert [document.semantic_identifier for document in documents] == ["src/main.py"]
    assert documents[0].id == (
        "https://gitlab.example/owner/repo/blob/main/src/main.py"
    )


def test_binary_file_returns_connector_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _connector(code_file_patterns=["*.py"])
    _use_archive(monkeypatch, connector, _tar_bytes({"binary.py": b"\x00\x01\x02"}))
    project = MagicMock(web_url="https://gitlab.example/owner/repo")

    results = list(connector._fetch_code_files(project, "main", "sha", None))

    assert len(results) == 1
    assert isinstance(results[0], ConnectorFailure)
    assert results[0].failed_document is not None
    assert results[0].failed_document.document_id.endswith("/binary.py")


def test_oversized_file_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = _connector(code_file_patterns=["*.py"])
    monkeypatch.setattr(gitlab_connector_module, "MAX_INDEXED_FILE_SIZE_BYTES", 2)
    _use_archive(monkeypatch, connector, _tar_bytes({"large.py": b"123"}))
    project = MagicMock(web_url="https://gitlab.example/owner/repo")

    assert list(connector._fetch_code_files(project, "main", "sha", None)) == []
