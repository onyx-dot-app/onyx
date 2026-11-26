from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.gitlab.connector import GitlabConnector
from onyx.connectors.models import Document, HierarchyNode

_FILES = [
    "README.md",
    "poetry.lock",
    "sub/uv.lock",
    "src/main.py",
    "src/logs/y.txt",
    "logs/x.txt",
    ".github/workflows/ci.yml",
    ".pre-commit-config.yaml",
    "docs/index.md",
    "docs/guide/intro.md",
]


def _fake_tree(paths: list[str]) -> dict[str, list[dict[str, str]]]:
    """Map each directory path to its direct children, GitLab tree style."""
    tree: dict[str, list[dict[str, str]]] = {"": []}
    seen: set[str] = set()
    for path in paths:
        parts = path.split("/")
        for i in range(len(parts)):
            current = "/".join(parts[: i + 1])
            if current in seen:
                continue
            seen.add(current)
            parent = "/".join(parts[:i])
            is_blob = i == len(parts) - 1
            if not is_blob:
                tree[current] = []
            tree[parent].append(
                {
                    "id": current,
                    "name": parts[i],
                    "path": current,
                    "type": "blob" if is_blob else "tree",
                }
            )
    return tree


def _index(
    excluded_paths: list[str] | None,
) -> tuple[set[str], list[str]]:
    """Run a load and return (indexed file paths, directories listed)."""
    tree = _fake_tree(_FILES)
    listed: list[str] = []

    def repository_tree(path: str, all: bool) -> list[dict[str, str]]:  # noqa: A002
        assert all
        listed.append(path)
        return tree[path]

    project = MagicMock()
    project.repository_tree.side_effect = repository_tree
    client = MagicMock()
    client.projects.get.return_value = project

    connector = GitlabConnector(
        "owner",
        "repo",
        include_mrs=False,
        include_issues=False,
        include_code_files=True,
        excluded_paths=excluded_paths,
    )
    connector.gitlab_client = client

    def fake_convert(_project: Any, file: dict[str, str], *_: Any) -> Document:
        return MagicMock(spec=Document, id=file["path"])

    with patch(
        "onyx.connectors.gitlab.connector._convert_code_to_document",
        side_effect=fake_convert,
    ):
        batches: list[list[Document | HierarchyNode]] = list(
            connector.load_from_state()
        )
    indexed = {
        doc.id for batch in batches for doc in batch if isinstance(doc, Document)
    }
    return indexed, listed


_DEFAULT_EXCLUDED = {
    ".github/workflows/ci.yml",
    "logs/x.txt",
    "src/logs/y.txt",
    ".pre-commit-config.yaml",
}
_DOCS = {"docs/index.md", "docs/guide/intro.md"}


@pytest.mark.parametrize(
    "excluded_paths, extra_excluded",
    [
        pytest.param(None, set(), id="none_uses_defaults"),
        pytest.param([], set(), id="empty_still_uses_defaults"),
        pytest.param(["*.lock"], {"poetry.lock", "sub/uv.lock"}, id="glob_any_depth"),
        pytest.param(["docs/*"], _DOCS, id="dir_glob"),
        pytest.param(["docs/"], _DOCS, id="trailing_slash"),
    ],
)
def test_excluded_paths(
    excluded_paths: list[str] | None, extra_excluded: set[str]
) -> None:
    indexed, _ = _index(excluded_paths)
    # User patterns add to the defaults; they never replace them.
    assert indexed == set(_FILES) - _DEFAULT_EXCLUDED - extra_excluded
    assert {"README.md", "src/main.py"} <= indexed


def test_excluded_directory_is_not_traversed() -> None:
    _, listed = _index(["docs/", "logs"])
    assert "docs" not in listed
    assert "docs/guide" not in listed
    assert "logs" not in listed
    assert "src" in listed
