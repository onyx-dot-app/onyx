from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from onyx.server.manage import search_settings


def test_unstructured_key_requires_json_body() -> None:
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
    client = TestClient(app)
    with patch.object(search_settings, "update_unstructured_api_key") as update:
        response = client.put(route.path, json={"unstructured_api_key": "test-key"})
        assert response.status_code == 200
        update.assert_called_once_with("test-key")
        update.reset_mock()
        response = client.put(route.path, params={"unstructured_api_key": "test-key"})
        assert response.status_code == 422
        update.assert_not_called()


@pytest.mark.parametrize("key", ["", " \t\n"])
def test_empty_unstructured_key_is_not_stored(key: str) -> None:
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
    client = TestClient(app)
    with patch.object(search_settings, "update_unstructured_api_key") as update:
        response = client.put(route.path, json={"unstructured_api_key": key})
        assert response.status_code == 422
        update.assert_not_called()
