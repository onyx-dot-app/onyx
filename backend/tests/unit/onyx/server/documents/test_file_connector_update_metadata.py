"""files/update must keep the connector's metadata file when the metadata does
not change. A new metadata file dates every file later, so the next run
re-embeds every file in the connector."""

import json
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.server.documents import connector as connector_server
from onyx.server.documents.models import DocumentSource, InputType

CURRENT_METADATA = [{"filename": "described.txt", "team": "search"}]


def _add_file(
    monkeypatch: pytest.MonkeyPatch,
    new_metadata: list[dict[str, Any]] | None,
    current_metadata: list[dict[str, Any]] = CURRENT_METADATA,
) -> tuple[str | None, MagicMock]:
    """Adds new.txt, with ``new_metadata`` in its zip if given, to a connector
    whose metadata file ``meta-current`` holds ``current_metadata``."""
    connector = MagicMock(
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "file_locations": ["described", "plain"],
            "file_names": ["described.txt", "plain.txt"],
            "zip_metadata_file_id": "meta-current",
        },
        refresh_freq=None,
        prune_freq=None,
        check_freq=None,
        indexing_start=None,
    )
    connector.name = "files"
    stored = {"meta-current": current_metadata, "meta-zip": new_metadata}
    store = MagicMock()
    store.read_file.side_effect = lambda file_id, mode: BytesIO(  # noqa: ARG005
        json.dumps(stored[file_id]).encode()
    )
    store.save_file.return_value = "meta-saved"
    upload = MagicMock(
        file_paths=["new"],
        file_names=["new.txt"],
        zip_metadata_file_id="meta-zip" if new_metadata else None,
    )
    for name, stub in {
        "fetch_connector_by_id": MagicMock(return_value=connector),
        "_fetch_and_check_file_connector_cc_pair_permissions": MagicMock(),
        "get_default_file_store": MagicMock(return_value=store),
        "upload_files": MagicMock(return_value=upload),
        "update_connector": MagicMock(),
        "mark_ccpair_with_indexing_trigger": MagicMock(),
        "client_app": MagicMock(),
    }.items():
        monkeypatch.setattr(connector_server, name, stub)

    response = connector_server.update_connector_files(
        connector_id=1,
        files=[MagicMock()],
        file_ids_to_remove="[]",
        user=MagicMock(),
        db_session=MagicMock(),
    )
    return response.zip_metadata_file_id, store


def test_adding_a_file_without_metadata_keeps_the_metadata_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_file_id, store = _add_file(monkeypatch, new_metadata=None)

    assert metadata_file_id == "meta-current"
    store.save_file.assert_not_called()


def test_adding_a_file_with_metadata_saves_the_merged_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_file_id, store = _add_file(
        monkeypatch, new_metadata=[{"filename": "new.txt", "team": "docs"}]
    )

    assert metadata_file_id == "meta-saved"
    saved = json.loads(store.save_file.call_args.kwargs["content"].getvalue())
    assert set(saved) == {"described.txt", "new.txt"}


def test_a_value_of_another_type_saves_the_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1 == True in Python, but the tags differ: "1" and "True"."""
    metadata_file_id, _ = _add_file(
        monkeypatch,
        new_metadata=[{"filename": "described.txt", "priority": True}],
        current_metadata=[{"filename": "described.txt", "priority": 1}],
    )

    assert metadata_file_id == "meta-saved"
