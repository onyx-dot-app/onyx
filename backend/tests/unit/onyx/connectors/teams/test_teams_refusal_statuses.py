"""Teams' refusal check is the shared Graph classifier, so a locked or archived
team (423) is left out rather than retried, and its remedy does not ask for a
grant."""

from __future__ import annotations

from requests import Response
from requests.exceptions import HTTPError

from onyx.connectors.teams.refusals import channel_remedy, is_permanent


def _http_error(status_code: int) -> HTTPError:
    response = Response()
    response.status_code = status_code
    return HTTPError(response=response)


def test_locked_team_is_permanent_and_left_out() -> None:
    error = _http_error(423)
    assert is_permanent(error) is True
    assert "Grant" not in channel_remedy("files", error)


def test_missing_grant_is_permanent_and_names_the_grant() -> None:
    error = _http_error(403)
    assert is_permanent(error) is True
    assert "Grant Files.Read.All or Sites.Read.All" in channel_remedy("files", error)


def test_expired_token_and_gone_page_fail_the_attempt() -> None:
    assert is_permanent(_http_error(401)) is False
    assert is_permanent(_http_error(410)) is False
