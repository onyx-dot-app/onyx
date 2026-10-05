"""The file connector's planning rule indexes only the files whose document is
new or changed, and prunes only when a document of the old config is gone."""

from typing import Any

from onyx.connectors.file.config import LocalFileConnectorConfig
from onyx.connectors.file.edit_planning import FilePlanningData, file_planning_rule
from onyx.connectors.planning_rule import RuleSteps
from onyx.file_store.models import StoredFileFacts

_PLANNED_FIELDS = frozenset({"file_locations", "zip_metadata_file_id", "zip_metadata"})


def _facts(name: str, sha: str | None) -> StoredFileFacts:
    return StoredFileFacts(
        display_name=name, file_type="text/plain", content_sha256=sha
    )


_FILES = {
    "f1": _facts("a.txt", "sha-a"),
    "f2": _facts("b.txt", "sha-b"),
    "f3": _facts("c.txt", "sha-c"),
    # Same bytes and name as f1, uploaded again.
    "f1-again": _facts("a.txt", "sha-a"),
    # Uploaded before hashes were recorded.
    "legacy": _facts("d.txt", None),
    "legacy-again": _facts("d.txt", None),
}


def _config(file_ids: list[str], **extra: Any) -> LocalFileConnectorConfig:
    return LocalFileConnectorConfig(
        file_locations=file_ids, file_names=[f"name-{f}" for f in file_ids], **extra
    )


def _steps(
    old: LocalFileConnectorConfig,
    new: LocalFileConnectorConfig,
    old_metadata: dict[str, Any] | None = None,
    new_metadata: dict[str, Any] | None = None,
) -> RuleSteps | None:
    override = file_planning_rule(
        old,
        new,
        FilePlanningData(
            files=_FILES,
            old_metadata=old_metadata or {},
            new_metadata=new_metadata
            if new_metadata is not None
            else old_metadata or {},
        ),
    )
    return override.rule_steps if override else None


def _indexed(steps: RuleSteps | None) -> list[str] | None:
    assert steps is not None
    if steps.backfill_config is None:
        return None
    return steps.backfill_config["file_locations"]


def test_added_files_are_indexed_alone() -> None:
    steps = _steps(_config(["f1"]), _config(["f1", "f2", "f3"]))

    assert steps is not None
    assert steps.field_names == _PLANNED_FIELDS
    assert steps.backfill_config == _config(["f2", "f3"]).model_dump(mode="json")
    assert not steps.prune


def test_removed_files_prune_only() -> None:
    steps = _steps(_config(["f1", "f2"]), _config(["f1"]))

    assert _indexed(steps) is None
    assert steps is not None and steps.prune


def test_reupload_without_a_metadata_id_is_a_new_document() -> None:
    # The document id comes from the file id, so the old document goes.
    steps = _steps(_config(["f1"]), _config(["f1-again"]))

    assert _indexed(steps) == ["f1-again"]
    assert steps is not None and steps.prune


def test_reupload_with_the_same_metadata_id_changes_nothing() -> None:
    metadata = {"a.txt": {"id": "doc-a", "title": "A"}}
    steps = _steps(_config(["f1"]), _config(["f1-again"]), metadata)

    assert steps == RuleSteps(field_names=_PLANNED_FIELDS)


def test_reupload_without_a_hash_is_indexed() -> None:
    metadata = {"d.txt": {"id": "doc-d"}}
    steps = _steps(_config(["legacy"]), _config(["legacy-again"]), metadata)

    assert _indexed(steps) == ["legacy-again"]
    # Both give doc-d, so nothing is pruned.
    assert steps is not None and not steps.prune


def test_metadata_change_reindexes_only_the_changed_files() -> None:
    old_metadata = {"a.txt": {"title": "A"}, "b.txt": {"title": "B"}}
    new_metadata = {"a.txt": {"title": "A2"}, "b.txt": {"title": "B"}}
    steps = _steps(
        _config(["f1", "f2", "f3"], zip_metadata_file_id="meta-1"),
        _config(["f1", "f2", "f3"], zip_metadata_file_id="meta-2"),
        old_metadata,
        new_metadata,
    )

    assert _indexed(steps) == ["f1"]
    assert steps is not None and not steps.prune
    assert steps.backfill_config is not None
    assert steps.backfill_config["zip_metadata_file_id"] == "meta-2"


def test_new_metadata_file_with_the_same_entries_changes_nothing() -> None:
    metadata = {"a.txt": {"title": "A"}}
    steps = _steps(
        _config(["f1"], zip_metadata_file_id="meta-1"),
        _config(["f1"], zip_metadata_file_id="meta-2"),
        metadata,
        dict(metadata),
    )

    assert steps == RuleSteps(field_names=_PLANNED_FIELDS)


def test_metadata_id_change_reindexes_and_prunes() -> None:
    steps = _steps(
        _config(["f1"], zip_metadata_file_id="meta-1"),
        _config(["f1"], zip_metadata_file_id="meta-2"),
        {"a.txt": {"id": "doc-a"}},
        {"a.txt": {"id": "doc-a2"}},
    )

    assert _indexed(steps) == ["f1"]
    assert steps is not None and steps.prune


def test_combined_edit() -> None:
    # f1 stays with new metadata, f2 goes, f3 is added; the zip also carries
    # an entry for the added file.
    steps = _steps(
        _config(["f1", "f2"], zip_metadata_file_id="meta-1"),
        _config(["f1", "f3"], zip_metadata_file_id="meta-2"),
        {"a.txt": {"title": "A"}},
        {"a.txt": {"title": "A2"}, "c.txt": {"title": "C"}},
    )

    assert _indexed(steps) == ["f1", "f3"]
    assert steps is not None and steps.prune
    assert steps.backfill_config is not None
    assert steps.backfill_config["file_names"] == ["name-f1", "name-f3"]


def test_file_without_a_record_gives_no_step() -> None:
    steps = _steps(_config(["f1"]), _config(["f1", "missing"]))

    assert steps == RuleSteps(field_names=_PLANNED_FIELDS)


def test_display_name_edit_uses_the_default_rules() -> None:
    old = _config(["f1"])
    new = old.model_copy(update={"file_names": ["renamed"]})

    assert _steps(old, new) is None
