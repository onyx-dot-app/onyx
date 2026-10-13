"""The team and project filters narrow the issue walk to the configured
teams and projects, and connector creation names any team or project Linear
does not answer for."""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.linear.config import LinearConnectorConfig
from onyx.connectors.linear.connector import LinearConnector

OPS: str = "onyx.connectors.linear.source_operations"
PROJECT_URL: str = "https://linear.app/acme/project/chat-ui-improvements-f90f2bc07871"
LAST_PAGE: dict[str, Any] = {"hasNextPage": False, "endCursor": None}


def _connector(
    team_keys: list[str] | None, projects: list[str] | None = None
) -> LinearConnector:
    connector = LinearConnector(team_keys=team_keys, projects=projects)
    connector.load_credentials({"linear_api_key": "lin_api_test"})
    return connector


def _teams_response(*keys: str, page_info: dict[str, Any] = LAST_PAGE) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {
        "data": {
            "teams": {"nodes": [{"key": key} for key in keys], "pageInfo": page_info}
        }
    }
    return response


def _projects_response(*projects: tuple[str, str]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {
        "data": {
            "projects": {
                "nodes": [
                    {"name": name, "slugId": slug_id} for name, slug_id in projects
                ],
                "pageInfo": LAST_PAGE,
            }
        }
    }
    return response


def test_stored_config_drops_blank_entries_and_upper_cases_keys() -> None:
    config = LinearConnectorConfig.model_validate(
        {"team_keys": ["eng", " ", "DES"], "projects": [" Roadmap ", "", PROJECT_URL]}
    )

    assert config.team_keys == ["DES", "ENG"]
    assert config.projects == ["Roadmap", PROJECT_URL]


def test_stored_config_rejects_non_string_entries_as_a_field_error() -> None:
    with pytest.raises(ValidationError, match="team_keys"):
        LinearConnectorConfig.model_validate({"team_keys": ["ENG", None]})


def test_keys_are_upper_cased_deduplicated_and_sorted() -> None:
    assert _connector(["eng", " ENG ", "design", ""]).team_keys == ["DESIGN", "ENG"]


def test_project_urls_become_slug_ids_and_names_stay_names() -> None:
    connector = _connector(
        None, ["Roadmap ", PROJECT_URL, f"{PROJECT_URL}/overview", ""]
    )

    assert connector.project_names == ["Roadmap"]
    assert connector.project_slug_ids == ["f90f2bc07871"]


def test_filter_carries_the_teams_and_the_poll_window() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)

    assert _connector(["ENG"])._issue_filter(start, end) == {
        "updatedAt": {"gte": start.isoformat(), "lte": end.isoformat()},
        "team": {"key": {"in": ["ENG"]}},
    }


def test_project_filter_joins_names_and_slug_ids_with_or() -> None:
    assert _connector(["ENG"], ["Roadmap", PROJECT_URL])._issue_filter() == {
        "updatedAt": {},
        "team": {"key": {"in": ["ENG"]}},
        "project": {
            "or": [
                {"name": {"in": ["Roadmap"]}},
                {"slugId": {"in": ["f90f2bc07871"]}},
            ]
        },
    }


def test_names_alone_need_no_or() -> None:
    assert _connector(None, ["Roadmap"])._issue_filter()["project"] == {
        "name": {"in": ["Roadmap"]}
    }


def test_no_scope_means_no_team_or_project_clause() -> None:
    assert _connector([])._issue_filter() == {"updatedAt": {}}


def test_validation_skips_linear_when_nothing_is_scoped() -> None:
    with patch(f"{OPS}._make_query") as query:
        _connector(None).validate_connector_settings()

    query.assert_not_called()


def test_validation_passes_when_linear_answers_for_every_entry() -> None:
    responses = [
        _teams_response("DES", "ENG"),
        _projects_response(("Roadmap", "f90f2bc07871")),
    ]
    with patch(f"{OPS}._make_query", side_effect=responses) as query:
        _connector(["ENG", "DES"], [PROJECT_URL]).validate_connector_settings()

    assert query.call_args_list[1].args[0]["variables"] == {
        "filter": {"slugId": {"in": ["f90f2bc07871"]}},
        "first": 100,
        "after": None,
    }


def test_validation_names_the_keys_linear_did_not_answer_for() -> None:
    with (
        patch(f"{OPS}._make_query", return_value=_teams_response("ENG")),
        pytest.raises(ConnectorValidationError, match="not found: DES, OPS"),
    ):
        _connector(["ENG", "OPS", "DES"]).validate_connector_settings()


def test_validation_names_missing_teams_and_projects_together() -> None:
    responses = [
        _teams_response("ENG"),
        _projects_response(("Roadmap", "aaaaaaaaaaaa")),
    ]
    with (
        patch(f"{OPS}._make_query", side_effect=responses),
        pytest.raises(
            ConnectorValidationError,
            match=r"teams not found: OPS\. Linear projects not found: Gone\.",
        ),
    ):
        _connector(["ENG", "OPS"], ["Roadmap", "Gone"]).validate_connector_settings()


def test_validation_follows_the_teams_cursor_to_the_last_page() -> None:
    responses = [
        _teams_response("ENG", page_info={"hasNextPage": True, "endCursor": "c1"}),
        _teams_response("DES"),
    ]
    with patch(f"{OPS}._make_query", side_effect=responses) as query:
        _connector(["ENG", "DES"]).validate_connector_settings()

    sent: list[str | None] = [
        call.args[0]["variables"]["after"] for call in query.call_args_list
    ]
    assert sent == [None, "c1"]


def test_validation_names_the_projects_linear_did_not_answer_for() -> None:
    with (
        patch(
            f"{OPS}._make_query",
            return_value=_projects_response(("Roadmap", "aaaaaaaaaaaa")),
        ),
        pytest.raises(ConnectorValidationError, match="not found: Gone, f90f2bc07871"),
    ):
        _connector(None, ["Roadmap", "Gone", PROJECT_URL]).validate_connector_settings()


def test_graphql_errors_are_raised_not_read_as_empty() -> None:
    response = MagicMock()
    response.json.return_value = {
        "errors": [{"message": "Query too complex"}],
        "data": None,
    }
    with (
        patch(f"{OPS}._make_query", return_value=response),
        pytest.raises(RuntimeError, match="Query too complex"),
    ):
        _connector(["ENG"]).validate_connector_settings()


def test_the_issue_walk_sends_the_filter_as_a_variable() -> None:
    page: dict[str, Any] = {"data": {"issues": {"nodes": [], "pageInfo": LAST_PAGE}}}
    response = MagicMock()
    response.json.return_value = page
    with patch(f"{OPS}._make_query", return_value=response) as query:
        batches = list(_connector(["ENG"]).load_from_state())

    assert batches == [[]]
    sent = query.call_args.args[0]
    assert sent["variables"]["filter"] == {
        "updatedAt": {},
        "team": {"key": {"in": ["ENG"]}},
    }
    assert "$filter: IssueFilter" in sent["query"]
