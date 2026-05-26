from unittest.mock import MagicMock

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.connectors.discourse.connector import discourse_request
from onyx.connectors.discourse.connector import DiscourseConnector
from onyx.connectors.discourse.connector import DiscoursePerms


def test_discourse_request_omits_empty_auth_headers(monkeypatch) -> None:
    response = MagicMock()
    mock_get = MagicMock(return_value=response)
    monkeypatch.setattr("onyx.connectors.discourse.connector.requests.get", mock_get)

    discourse_request(
        "https://forum.example.com/latest.json",
        DiscoursePerms(api_key="", api_username=""),
        params={"page": 1},
    )

    response.raise_for_status.assert_called_once()
    mock_get.assert_called_once_with(
        "https://forum.example.com/latest.json",
        headers={},
        params={"page": 1},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


def test_discourse_request_only_sends_non_empty_auth_headers(monkeypatch) -> None:
    response = MagicMock()
    mock_get = MagicMock(return_value=response)
    monkeypatch.setattr("onyx.connectors.discourse.connector.requests.get", mock_get)

    discourse_request(
        "https://forum.example.com/latest.json",
        DiscoursePerms(api_key="discourse-key", api_username=""),
    )

    mock_get.assert_called_once_with(
        "https://forum.example.com/latest.json",
        headers={"Api-Key": "discourse-key"},
        params=None,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


def test_get_categories_map_includes_subcategories_when_parent_matches() -> None:
    connector = DiscourseConnector(
        base_url="https://forum.example.com",
        categories=["Walt Disney World"],
    )
    connector.permissions = DiscoursePerms(api_key="", api_username="")

    response = MagicMock()
    response.json.return_value = {
        "category_list": {
            "categories": [
                {
                    "id": 1,
                    "name": "Walt Disney World",
                    "slug": "walt-disney-world",
                    "subcategory_list": [
                        {"id": 2, "name": "Dining", "slug": "dining"},
                        {
                            "id": 3,
                            "name": "Accommodations",
                            "slug": "accommodations",
                        },
                    ],
                },
                {
                    "id": 4,
                    "name": "Disneyland",
                    "slug": "disneyland",
                    "subcategory_list": [
                        {
                            "id": 5,
                            "name": "Disneyland Dining",
                            "slug": "disneyland-dining",
                        }
                    ],
                },
            ]
        }
    }
    connector._make_request = MagicMock(return_value=response)  # type: ignore[method-assign]

    connector._get_categories_map()

    assert connector.category_id_map == {
        1: {"name": "Walt Disney World", "slug": "walt-disney-world"},
        2: {"name": "Dining", "slug": "dining"},
        3: {"name": "Accommodations", "slug": "accommodations"},
    }
    assert connector.active_categories == {1, 2, 3}


def test_get_categories_map_can_filter_directly_to_subcategory() -> None:
    connector = DiscourseConnector(
        base_url="https://forum.example.com",
        categories=["Dining"],
    )
    connector.permissions = DiscoursePerms(api_key="", api_username="")

    response = MagicMock()
    response.json.return_value = {
        "category_list": {
            "categories": [
                {
                    "id": 1,
                    "name": "Walt Disney World",
                    "slug": "walt-disney-world",
                    "subcategory_list": [
                        {"id": 2, "name": "Dining", "slug": "dining"},
                    ],
                },
            ]
        }
    }
    connector._make_request = MagicMock(return_value=response)  # type: ignore[method-assign]

    connector._get_categories_map()

    assert connector.category_id_map == {2: {"name": "Dining", "slug": "dining"}}
    assert connector.active_categories == {2}
