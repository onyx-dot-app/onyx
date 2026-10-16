from typing import Any
from unittest.mock import ANY, patch

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from onyx.server.manage import search_settings
from onyx.server.manage.api_token.models import ExistingApiToken, NewApiToken


def _client() -> tuple[TestClient, str]:
    app = FastAPI()
    app.include_router(search_settings.router)
    route = next(
        route
        for route in search_settings.router.routes
        if isinstance(route, APIRoute)
        and route.path.endswith("/upsert-unstructured-api-key")
    )
    for dependency in route.dependant.dependencies:
        assert dependency.call is not None
        app.dependency_overrides[dependency.call] = lambda: None
    return TestClient(app), route.path


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"api_key": "test-key"}, NewApiToken(value="test-key")),
        (
            {"api_key": {"type": "new", "value": "test-key"}},
            NewApiToken(value="test-key"),
        ),
        ({"api_key": {"type": "existing", "id": 3}}, ExistingApiToken(id=3)),
    ],
)
def test_unstructured_key_takes_token_input_in_json_body(
    body: dict[str, Any], expected: NewApiToken | ExistingApiToken
) -> None:
    client, path = _client()
    with patch.object(search_settings, "update_unstructured_api_key") as update:
        response = client.put(path, json=body)
        assert response.status_code == 200
        update.assert_called_once_with(ANY, expected)
        update.reset_mock()
        response = client.put(path, params={"api_key": "test-key"})
        assert response.status_code == 422
        update.assert_not_called()


@pytest.mark.parametrize("key", ["", " \t\n"])
def test_empty_unstructured_key_is_not_stored(key: str) -> None:
    client, path = _client()
    with patch.object(search_settings, "update_unstructured_api_key") as update:
        response = client.put(path, json={"api_key": {"type": "new", "value": key}})
        assert response.status_code == 422
        update.assert_not_called()
