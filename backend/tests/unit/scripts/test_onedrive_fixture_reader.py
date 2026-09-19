"""Tests for read-only OneDrive fixture discovery."""

from unittest.mock import MagicMock

from tests.utils.onedrive_fixture import (
    DAILY_FIXTURE_ROOT_NAME,
    INTEGRATION_FIXTURE_ROOT_NAME,
    FixtureGraphReader,
    GraphDrive,
    GraphItem,
    GraphSite,
    GraphUser,
    OneDriveFixtureReader,
    SharePointIds,
    build_daily_fixture_config,
    build_integration_fixture_config,
)


def _reader() -> tuple[OneDriveFixtureReader, MagicMock]:
    graph = MagicMock(spec=FixtureGraphReader)
    reader = OneDriveFixtureReader(build_daily_fixture_config(), graph)
    return reader, graph


def test_read_only_suite_configs_use_distinct_corpora() -> None:
    daily = build_daily_fixture_config().corpus
    integration = build_integration_fixture_config().corpus

    assert daily.root_name == DAILY_FIXTURE_ROOT_NAME
    assert integration.root_name == INTEGRATION_FIXTURE_ROOT_NAME
    assert daily.root_name != integration.root_name
    assert daily.visible_group.mail_nickname != integration.visible_group.mail_nickname
    assert daily.hidden_group.mail_nickname != integration.hidden_group.mail_nickname


def test_fixture_configs_are_immutable() -> None:
    config = build_daily_fixture_config()

    assert config.model_config.get("frozen") is True
    assert config.corpus.model_config.get("frozen") is True


def test_fixture_graph_reader_exposes_no_write_operations() -> None:
    assert not hasattr(FixtureGraphReader, "post")
    assert not hasattr(FixtureGraphReader, "put")
    assert not hasattr(FixtureGraphReader, "patch")
    assert not hasattr(FixtureGraphReader, "delete")


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
        [],
        [
            {
                "id": "visible",
                "displayName": corpus.visible_group.display_name,
                "mailNickname": corpus.visible_group.mail_nickname,
                "description": corpus.ownership_description,
                "visibility": corpus.visible_group.visibility.value,
            }
        ],
        [
            {
                "id": "hidden",
                "displayName": corpus.hidden_group.display_name,
                "mailNickname": corpus.hidden_group.mail_nickname,
                "description": corpus.ownership_description,
                "visibility": corpus.hidden_group.visibility.value,
            }
        ],
    ]

    state = reader.load_state()

    assert state.drive.id == "drive"
    assert state.second_drive.id == "second-drive"
