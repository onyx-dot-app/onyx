import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from onyx.server.auth_check import is_route_in_spec_list
from onyx.server.auth_check import PUBLIC_ENDPOINT_SPECS
from onyx.server.lti import registration


@pytest.mark.parametrize(
    "configured_domain",
    ["https://tutor.example.edu", "https://learning.example.org/onyx"],
)
@pytest.mark.parametrize("trailing_slash", ["", "/"])
def test_public_registration_uses_configured_domain(
    configured_domain: str, trailing_slash: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registration, "WEB_DOMAIN", configured_domain + trailing_slash)
    # Registration must work before Canvas assigns client and deployment IDs.
    for name in ("LTI_CLIENT_ID", "LTI_DEPLOYMENT_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LTI_CANVAS_OAUTH_CLIENT_SECRET", "must-not-be-published")

    app = FastAPI()
    app.include_router(registration.router)
    with TestClient(app) as client:
        response = client.get(
            "/auth/lti/registration.json",
            headers={
                "Host": "untrusted.example",
                "X-Forwarded-Host": "untrusted.example",
                "X-Forwarded-Proto": "http",
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "no-store"
    metadata = response.json()
    assert metadata["title"] == "Onyx AI Tutor"
    assert metadata["oidc_initiation_url"] == f"{configured_domain}/auth/lti/login"
    assert metadata["target_link_uri"] == f"{configured_domain}/auth/lti/launch"
    assert metadata["public_jwk_url"] == f"{configured_domain}/auth/lti/jwks"
    assert metadata["scopes"] == [
        "https://purl.imsglobal.org/spec/lti-nrps/scope/contextmembership.readonly"
    ]
    extension = metadata["extensions"][0]
    assert extension["tool_id"] == "onyx-learning-assistant"
    assert extension["domain"] in {"tutor.example.edu", "learning.example.org"}
    assert extension["settings"]["icon_url"] == f"{configured_domain}/logo.png"
    placements = extension["settings"]["placements"]
    assert {placement["placement"] for placement in placements} == {
        "link_selection",
        "course_navigation",
    }
    assert all(
        placement["target_link_uri"] == f"{configured_domain}/auth/lti/launch"
        for placement in placements
    )
    assert metadata["custom_fields"]["course_id"] == "$Canvas.course.id"
    assert "untrusted.example" not in response.text
    assert "must-not-be-published" not in response.text
    route = next(
        route
        for route in registration.router.routes
        if getattr(route, "path", None) == "/auth/lti/registration.json"
    )
    assert is_route_in_spec_list(route, PUBLIC_ENDPOINT_SPECS)
