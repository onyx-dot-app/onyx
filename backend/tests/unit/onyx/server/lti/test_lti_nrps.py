from unittest.mock import patch

import httpx
import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.server.lti.nrps import fetch_nrps_roster


@pytest.mark.parametrize(
    "failure", ["missing_members", "invalid_member", "page_limit", "upstream"]
)
def test_incomplete_roster_raises_instead_of_returning_partial_permissions(
    failure: str,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            if failure == "missing_members":
                return httpx.Response(200, json={"error": "Roster unavailable"})
            if failure == "invalid_member":
                return httpx.Response(200, json={"members": ["invalid"]})
            return httpx.Response(403)
        return httpx.Response(
            200,
            json={"members": [{"email": "student@school.edu", "status": "Active"}]},
            headers={"Link": '<https://canvas.test/roster?page=2>; rel="next"'},
        )

    client = httpx.Client(transport=httpx.MockTransport(respond))
    with (
        patch("onyx.server.lti.nrps.mint_lti_service_token", return_value="test-token"),
        patch("onyx.server.lti.nrps.httpx.Client", return_value=client),
        patch(
            "onyx.server.lti.nrps._MAX_NRPS_PAGES",
            1 if failure == "page_limit" else 100,
        ),
        pytest.raises(OnyxError),
    ):
        fetch_nrps_roster("https://canvas.test/roster")


def test_complete_roster_paginates_and_ignores_inactive_and_email_less_members() -> (
    None
):
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(
                200,
                json={
                    "members": [
                        {"email": "teacher@school.edu", "status": "Active"},
                        {"email": "former@school.edu", "status": "Inactive"},
                        {"status": "Active"},
                    ]
                },
            )
        return httpx.Response(
            200,
            json={"members": [{"email": " Student@School.edu ", "status": "Active"}]},
            headers={"Link": '<https://canvas.test/roster?page=2>; rel="next"'},
        )

    client = httpx.Client(transport=httpx.MockTransport(respond))
    with (
        patch("onyx.server.lti.nrps.mint_lti_service_token", return_value="test-token"),
        patch("onyx.server.lti.nrps.httpx.Client", return_value=client),
    ):
        roster = fetch_nrps_roster("https://canvas.test/roster")
    assert roster.active_member_emails() == {"student@school.edu", "teacher@school.edu"}
