"""Tests for Asana connector configuration parsing."""

import pytest

from onyx.connectors.asana.connector import AsanaConnector


@pytest.mark.parametrize(
    "project_ids,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        (" 123 ", ["123"]),
        (" 123 , , 456 , ", ["123", "456"]),
    ],
)
def test_asana_connector_project_ids_normalization(
    project_ids: str | None, expected: list[str] | None
) -> None:
    connector = AsanaConnector(
        asana_workspace_id=" 1153293530468850 ",
        asana_project_ids=project_ids,
        asana_team_id=" 1210918501948021 ",
    )

    assert connector.workspace_id == "1153293530468850"
    assert connector.project_ids_to_index == expected
    assert connector.asana_team_id == "1210918501948021"


def test_asana_connector_team_id_empty_string() -> None:
    connector = AsanaConnector(
        asana_workspace_id="1153293530468850",
        asana_project_ids=None,
        asana_team_id="   ",
    )

    assert connector.asana_team_id is None
