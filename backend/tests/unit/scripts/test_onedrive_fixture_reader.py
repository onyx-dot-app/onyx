"""Tests for read-only OneDrive fixture discovery."""

from unittest.mock import MagicMock

import pytest

from tests.utils.onedrive_fixture import (
    FIXTURE_EXCLUDED_PATHS,
    FIXTURE_ROOT_NAME,
    FixtureGraphReader,
    GraphDrive,
    GraphItem,
    GraphSite,
    GraphUser,
    OneDriveFixtureReader,
    SharePointIds,
    load_fixture_config,
)


def _reader() -> tuple[OneDriveFixtureReader, MagicMock]:
    graph = MagicMock(spec=FixtureGraphReader)
    reader = OneDriveFixtureReader(load_fixture_config(), graph)
    return reader, graph


def test_read_only_config_targets_existing_corpus() -> None:
    assert load_fixture_config().corpus.root_name == FIXTURE_ROOT_NAME


def test_fixture_configs_are_immutable() -> None:
    config = load_fixture_config()

    assert config.model_config.get("frozen") is True
    assert config.corpus.model_config.get("frozen") is True


def test_fixture_graph_reader_exposes_no_write_operations() -> None:
    assert not hasattr(FixtureGraphReader, "post")
    assert not hasattr(FixtureGraphReader, "put")
    assert not hasattr(FixtureGraphReader, "patch")
    assert not hasattr(FixtureGraphReader, "delete")


def test_fixture_graph_reader_rejects_repeated_collection_cursor() -> None:
    graph = FixtureGraphReader(MagicMock(), "https://graph.example.test")
    graph.get_json = MagicMock(
        return_value={
            "value": [],
            "@odata.nextLink": "https://graph.example.test/v1.0/users",
        }
    )

    with pytest.raises(RuntimeError, match="cursor did not advance"):
        graph.get_collection("users")


def test_load_state_reads_existing_fixture() -> None:
    reader, graph = _reader()
    users = [
        GraphUser.model_validate(
            {"id": user_id, "userPrincipalName": f"{user_id}@example.com"}
        )
        for user_id in ("owner", "second-owner", "primary", "alternate")
    ]
    drives = [
        GraphDrive.model_validate(
            {
                "id": drive_id,
                "name": drive_id,
                "webUrl": f"https://example.test/{drive_id}",
                "driveType": "business",
                "sharepointIds": {"siteId": "site"},
            }
        )
        for drive_id in ("drive", "second-drive")
    ]
    graph.get_model.side_effect = [
        *users,
        *drives,
        GraphSite.model_validate({"id": "site", "webUrl": "https://example.test/site"}),
    ]
    graph.get_optional_item.side_effect = lambda path: GraphItem.model_validate(
        {
            "id": path,
            "name": path.rsplit("/", 1)[-1],
            "webUrl": f"https://example.test/{path}",
            "sharepointIds": SharePointIds.model_validate(
                {"siteId": "site"}
            ).model_dump(by_alias=True),
        }
    )
    corpus = reader.config.corpus
    graph.get_collection.side_effect = [
        [
            {
                "id": "fixture-root",
                "name": corpus.root_name,
                "webUrl": "https://example.test/fixture-root",
                "folder": {},
            },
            {
                "id": "other-folder",
                "name": "Other folder",
                "webUrl": "https://example.test/other-folder",
                "folder": {},
            },
        ],
        [
            {
                "id": "other-file",
                "name": "other.docx",
                "webUrl": "https://example.test/other.docx",
                "file": {},
            }
        ],
        [],
        [
            {
                "id": "visible",
                "displayName": corpus.visible_group.display_name,
                "mailNickname": corpus.visible_group.mail_nickname,
                "visibility": corpus.visible_group.visibility.value,
            }
        ],
        [
            {
                "id": "hidden",
                "displayName": corpus.hidden_group.display_name,
                "mailNickname": corpus.hidden_group.mail_nickname,
                "visibility": corpus.hidden_group.visibility.value,
            }
        ],
    ]

    state = reader.load_state()

    assert state.drive.id == "drive"
    assert state.second_drive.id == "second-drive"
    assert state.excluded_paths == sorted(
        [*FIXTURE_EXCLUDED_PATHS, "Other folder", "Other folder/*", "other.docx"]
    )
