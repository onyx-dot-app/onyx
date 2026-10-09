"""graph_api_get_json merges caller headers under the Authorization it sets."""

from unittest.mock import MagicMock, patch

from onyx.connectors.microsoft_utils.graph_client import graph_api_get_json

MODULE = "onyx.connectors.microsoft_utils.graph_client"


def _ok_response() -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.json.return_value = {"value": []}
    return response


def test_preferences_ride_along_with_the_bearer_token() -> None:
    with patch(f"{MODULE}.requests.get", return_value=_ok_response()) as get:
        graph_api_get_json(
            lambda: "tok",
            "https://graph.microsoft.com/v1.0/users",
            {"$top": "1"},
            {"Prefer": "odata.maxpagesize=1"},
        )

    assert get.call_args.kwargs["headers"] == {
        "Prefer": "odata.maxpagesize=1",
        "Authorization": "Bearer tok",
    }
    assert get.call_args.kwargs["params"] == {"$top": "1"}


def test_callers_cannot_replace_the_authorization_header() -> None:
    with patch(f"{MODULE}.requests.get", return_value=_ok_response()) as get:
        graph_api_get_json(
            lambda: "tok",
            "https://graph.microsoft.com/v1.0/users",
            headers={"Authorization": "Basic nope"},
        )

    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"
