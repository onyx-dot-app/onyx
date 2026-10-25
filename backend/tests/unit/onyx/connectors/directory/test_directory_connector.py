"""Unit tests for the Directory connector.

Covers configuration validation, the allowed-roots guard, recursive
checkpointed walking, filtering, slim-document generation for pruning and
re-resolution of failed documents.
"""

import time
import unicodedata
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from onyx.connectors.directory.connector import (
    CurrentDirectory,
    DirectoryCheckpoint,
    DirectoryConnector,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import ConnectorFailure, Document, DocumentFailure

_ALLOWED_ROOTS_ENV = "DIRECTORY_CONNECTOR_ALLOWED_ROOTS"


@pytest.fixture(autouse=True)
def _no_unstructured_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep file processing offline: the KV store would hit the real DB."""
    import onyx.file_processing.extract_file_text as extract_file_text

    monkeypatch.setattr(extract_file_text, "get_unstructured_api_key", lambda: None)


def _drain(
    generator: Generator[Any, Any, DirectoryCheckpoint],
) -> tuple[list[Any], DirectoryCheckpoint]:
    """Collect everything a checkpointed connector yields plus its checkpoint."""
    results: list[Any] = []
    try:
        while True:
            results.append(next(generator))
    except StopIteration as stop:
        return results, stop.value


def _run_to_completion(
    connector: DirectoryConnector,
    start: float,
    end: float,
    checkpoint: DirectoryCheckpoint | None = None,
) -> list[Any]:
    """Drive the checkpoint loop until ``has_more`` is false."""
    checkpoint = checkpoint or connector.build_dummy_checkpoint()
    results: list[Any] = []
    while checkpoint.has_more:
        batch, checkpoint = _drain(
            connector.load_from_checkpoint(start, end, checkpoint)
        )
        results.extend(batch)
    return results


@pytest.fixture
def source_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "docs"
    root.mkdir()
    monkeypatch.setenv(_ALLOWED_ROOTS_ENV, str(tmp_path))
    return root


def _make_connector(root: Path, **kwargs: Any) -> DirectoryConnector:
    kwargs.setdefault("source_id", "docs")
    return DirectoryConnector(str(root), **kwargs)


def _documents(results: list[Any]) -> list[Document]:
    return [result for result in results if isinstance(result, Document)]


def test_invalid_source_id_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConnectorValidationError):
        _make_connector(tmp_path, source_id="Not A Valid Id!")


def test_root_outside_allowed_roots_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_ALLOWED_ROOTS_ENV, raising=False)
    connector = _make_connector(tmp_path)
    with pytest.raises(ConnectorValidationError):
        connector.validate_connector_settings()


def test_unavailable_root_rejected(source_root: Path) -> None:
    connector = DirectoryConnector(
        str(source_root / "does-not-exist"), source_id="docs"
    )
    with pytest.raises(ConnectorValidationError):
        connector.validate_connector_settings()


def test_recursive_walk_indexes_all_files(source_root: Path) -> None:
    (source_root / "a.txt").write_text("alpha")
    nested = source_root / "sub" / "deeper"
    nested.mkdir(parents=True)
    (nested / "b.md").write_text("# beta")

    connector = _make_connector(source_root, batch_size=10)
    results = _run_to_completion(connector, start=0, end=time.time() + 10)

    documents = _documents(results)
    relative_paths = {document.metadata["relative_path"] for document in documents}
    assert relative_paths == {"a.txt", "sub/deeper/b.md"}
    for document in documents:
        assert document.id.startswith("directory:docs:")
        assert document.semantic_identifier in {"a.txt", "sub/deeper/b.md"}


def test_checkpointing_yields_every_file_exactly_once(source_root: Path) -> None:
    for index in range(5):
        (source_root / f"file-{index}.txt").write_text(f"content {index}")

    connector = _make_connector(source_root, batch_size=1)
    results = _run_to_completion(connector, start=0, end=time.time() + 10)

    document_ids = [result.id for result in _documents(results)]
    assert len(document_ids) == 5
    assert len(set(document_ids)) == 5


def test_hidden_and_extension_filtering(source_root: Path) -> None:
    (source_root / "keep.txt").write_text("kept")
    (source_root / "skip.xyz").write_text("unsupported extension")
    (source_root / ".hidden.txt").write_text("hidden file")
    hidden_dir = source_root / ".secret"
    hidden_dir.mkdir()
    (hidden_dir / "nested.txt").write_text("hidden directory")

    connector = _make_connector(source_root, batch_size=10)
    results = _run_to_completion(connector, start=0, end=time.time() + 10)

    documents = _documents(results)
    assert [document.metadata["relative_path"] for document in documents] == [
        "keep.txt"
    ]


def test_include_and_exclude_patterns(source_root: Path) -> None:
    (source_root / "report-2024.txt").write_text("included")
    (source_root / "report-2024-draft.txt").write_text("excluded")
    (source_root / "other.txt").write_text("not matched by include")

    connector = _make_connector(
        source_root,
        batch_size=10,
        include_patterns=[r"report-"],
        exclude_patterns=[r"-draft"],
    )
    results = _run_to_completion(connector, start=0, end=time.time() + 10)

    documents = _documents(results)
    assert [document.metadata["relative_path"] for document in documents] == [
        "report-2024.txt"
    ]


def test_non_recursive_mode_ignores_subdirectories(source_root: Path) -> None:
    (source_root / "top.txt").write_text("top level")
    (source_root / "sub").mkdir()
    (source_root / "sub" / "nested.txt").write_text("nested")

    connector = _make_connector(source_root, batch_size=10, recursive=False)
    results = _run_to_completion(connector, start=0, end=time.time() + 10)

    documents = _documents(results)
    assert [document.metadata["relative_path"] for document in documents] == ["top.txt"]


def test_empty_file_yields_failure(source_root: Path) -> None:
    (source_root / "empty.txt").write_text("")

    connector = _make_connector(source_root, batch_size=10)
    results = _run_to_completion(connector, start=0, end=time.time() + 10)

    failures = [result for result in results if isinstance(result, ConnectorFailure)]
    assert len(failures) == 1
    assert "empty" in failures[0].failure_message


def test_oversized_file_yields_failure(source_root: Path) -> None:
    (source_root / "big.txt").write_bytes(b"x" * 1024)

    connector = _make_connector(source_root, batch_size=10, max_file_size_mb=1)
    connector.max_file_size_bytes = 512
    results = _run_to_completion(connector, start=0, end=time.time() + 10)

    failures = [result for result in results if isinstance(result, ConnectorFailure)]
    assert len(failures) == 1
    assert "max_file_size_mb" in failures[0].failure_message


def test_time_window_skips_unchanged_files(source_root: Path) -> None:
    path = source_root / "old.txt"
    path.write_text("content")
    # ctime cannot be backdated, so the file's change timestamp is "now";
    # a poll window that ended in the past must therefore exclude it.
    connector = _make_connector(source_root, batch_size=10)
    results = _run_to_completion(
        connector, start=time.time() - 120, end=time.time() - 60
    )
    assert _documents(results) == []

    # The same file is picked up by a window that covers the present.
    results = _run_to_completion(
        connector, start=time.time() - 120, end=time.time() + 10
    )
    assert len(_documents(results)) == 1


def test_document_ids_are_stable_across_instances(source_root: Path) -> None:
    (source_root / "doc.txt").write_text("stable")

    first = _make_connector(source_root)
    second = _make_connector(source_root)

    first_checkpoint = first.build_dummy_checkpoint()
    first_batch, _ = _drain(
        first.load_from_checkpoint(0, time.time() + 10, first_checkpoint)
    )
    second_checkpoint = second.build_dummy_checkpoint()
    second_batch, _ = _drain(
        second.load_from_checkpoint(0, time.time() + 10, second_checkpoint)
    )

    assert isinstance(first_batch[0], Document)
    assert isinstance(second_batch[0], Document)
    assert first_batch[0].id == second_batch[0].id


def test_slim_docs_cover_all_files(source_root: Path) -> None:
    for index in range(3):
        (source_root / f"f{index}.txt").write_text(f"{index}")

    connector = _make_connector(source_root, batch_size=2)
    slim_batches = list(
        connector.retrieve_all_slim_docs(start=None, end=None, callback=None)
    )

    slim_ids = [slim.id for batch in slim_batches for slim in batch]
    assert len(slim_ids) == 3
    assert len(set(slim_ids)) == 3
    assert len(slim_batches) == 2  # batch_size=2 -> batches of 2 and 1


def test_slim_preflight_enforces_minimum_prune_files(source_root: Path) -> None:
    (source_root / "only.txt").write_text("one file")

    connector = _make_connector(source_root, minimum_prune_files=5)
    with pytest.raises(ConnectorValidationError):
        list(connector.retrieve_all_slim_docs(start=None, end=None, callback=None))


def test_reindex_resolves_failures_via_document_link(source_root: Path) -> None:
    (source_root / "retry.txt").write_text("retry me")

    connector = _make_connector(source_root)
    document_id = connector._document_id("retry.txt")
    failure = ConnectorFailure(
        failed_document=DocumentFailure(
            document_id=document_id,
            document_link=connector._directory_uri("retry.txt"),
        ),
        failure_message="synthetic failure",
    )

    results = list(connector.reindex([failure]))
    documents = _documents(results)
    assert len(documents) == 1
    assert documents[0].metadata["relative_path"] == "retry.txt"


def test_reindex_passes_through_unresolvable_failures(source_root: Path) -> None:
    connector = _make_connector(source_root)
    failure = ConnectorFailure(
        failed_document=DocumentFailure(
            document_id="directory:docs:unknown",
            document_link=None,
        ),
        failure_message="synthetic failure",
    )
    results = list(connector.reindex([failure]))
    assert results == [failure]


def test_checkpoint_json_roundtrip(source_root: Path) -> None:
    connector = _make_connector(source_root)
    checkpoint = DirectoryCheckpoint(
        pending_directories=["sub"],
        current_directory=CurrentDirectory(
            relative_directory="sub", file_names=["a.txt"], offset=1
        ),
        has_more=True,
    )
    restored = connector.validate_checkpoint_json(checkpoint.model_dump_json())
    assert restored == checkpoint


def test_zero_max_file_size_is_unlimited(source_root: Path) -> None:
    """max_file_size_mb=0 disables the per-file size check entirely."""
    (source_root / "big.txt").write_bytes(b"x" * 2048)

    connector = _make_connector(source_root, batch_size=10, max_file_size_mb=0)
    connector.validate_connector_settings()
    results = _run_to_completion(connector, start=0, end=time.time() + 10)

    assert [r for r in results if isinstance(r, ConnectorFailure)] == []
    assert [r for r in results if isinstance(r, DocumentFailure)] == []
    assert len(_documents(results)) == 1


def test_zero_max_file_size_ignores_small_limits(source_root: Path) -> None:
    """A file far above a *set* limit fails; the same file passes with 0."""
    (source_root / "big.txt").write_bytes(b"x" * 4096)

    limited = _make_connector(source_root, batch_size=10, max_file_size_mb=1)
    limited.max_file_size_bytes = 1024
    results = _run_to_completion(limited, start=0, end=time.time() + 10)
    assert len([r for r in results if isinstance(r, ConnectorFailure)]) == 1

    unlimited = _make_connector(source_root, batch_size=10, max_file_size_mb=0)
    results = _run_to_completion(unlimited, start=0, end=time.time() + 10)
    assert len(_documents(results)) == 1
    assert not [
        r for r in results if isinstance(r, (ConnectorFailure, DocumentFailure))
    ]


def test_negative_max_file_size_rejected(source_root: Path) -> None:
    with pytest.raises(ConnectorValidationError):
        _make_connector(source_root, max_file_size_mb=-1)


def test_zero_max_directories_is_unlimited(source_root: Path) -> None:
    """max_directories_per_batch=0 removes the per-batch directory scan limit."""
    for index in range(3):
        directory = source_root / f"sub-{index}"
        directory.mkdir()
        (directory / "note.txt").write_text(f"content {index}")

    connector = _make_connector(source_root, batch_size=10, max_directories_per_batch=0)
    connector.validate_connector_settings()
    results = _run_to_completion(connector, start=0, end=time.time() + 10)

    assert len(_documents(results)) == 3
    assert [r for r in results if isinstance(r, ConnectorFailure)] == []


def test_negative_max_directories_rejected(source_root: Path) -> None:
    with pytest.raises(ConnectorValidationError):
        _make_connector(source_root, max_directories_per_batch=-1)


def test_connector_without_source_id_uses_derived_identity(source_root: Path) -> None:
    """The UI form does not send source_id; the connector must still work and
    derive a stable identity from the resolved root."""
    (source_root / "doc.txt").write_text("content")

    connector = DirectoryConnector(str(source_root))
    connector.validate_connector_settings()
    results = _run_to_completion(connector, start=0, end=time.time() + 10)
    documents = _documents(results)
    assert len(documents) == 1
    assert documents[0].id.startswith("directory:dir-")

    second = DirectoryConnector(str(source_root))
    second_results = _run_to_completion(second, start=0, end=time.time() + 10)
    second_documents = _documents(second_results)
    assert len(second_documents) == 1
    assert second_documents[0].id == documents[0].id


def test_explicit_source_id_still_wins_over_derivation(source_root: Path) -> None:
    (source_root / "doc.txt").write_text("content")

    connector = _make_connector(source_root, source_id="geodata")
    results = _run_to_completion(connector, start=0, end=time.time() + 10)
    documents = _documents(results)
    assert len(documents) == 1
    assert documents[0].id.startswith("directory:geodata:")


def test_connector_config_accepts_missing_source_id() -> None:
    """DirectoryConnectorConfig must validate UI-created configs (no source_id)."""
    from onyx.connectors.directory.config import DirectoryConnectorConfig

    config = DirectoryConnectorConfig.model_validate(
        {"root_directory": "/data/documents"}
    )
    assert config.source_id is None


def test_posix_backslash_filename_is_indexed(source_root: Path) -> None:
    """A literal backslash is a valid POSIX filename and must not silently
    drop the file (old code rewrote it to a path separator)."""
    name = "back\\slash.txt"
    (source_root / name).write_text("content")

    connector = _make_connector(source_root, batch_size=10)
    results = _run_to_completion(connector, start=0, end=time.time() + 10)

    documents = _documents(results)
    assert len(documents) == 1
    # The file must be indexed; its identity is the canonicalized form, the
    # filesystem access uses the raw name (see _absolute_path).
    assert documents[0].metadata["relative_path"] == "back/slash.txt"


def test_nfd_filename_is_indexed(source_root: Path) -> None:
    """NFD-stored names (e.g. macOS-created files on an NFS share) must not
    be silently dropped by NFC normalization before filesystem access."""
    name = unicodedata.normalize("NFD", "café.txt")
    (source_root / name).write_text("accented")

    connector = _make_connector(source_root, batch_size=10)
    results = _run_to_completion(connector, start=0, end=time.time() + 10)

    documents = _documents(results)
    assert len(documents) == 1
    assert documents[0].metadata["relative_path"] == unicodedata.normalize(
        "NFC", "café.txt"
    )


def test_reindex_resolves_raw_path_from_uri(source_root: Path) -> None:
    """Failures record the raw path in the URI so reindex resolves the name
    the filesystem stores (NFD case)."""
    name = unicodedata.normalize("NFD", "café.txt")
    (source_root / name).write_text("accented")

    connector = _make_connector(source_root)
    document_id = connector._document_id(name)
    failure = ConnectorFailure(
        failed_document=DocumentFailure(
            document_id=document_id,
            document_link=connector._directory_uri(name),
        ),
        failure_message="synthetic failure",
    )

    results = list(connector.reindex([failure]))
    documents = _documents(results)
    assert len(documents) == 1
