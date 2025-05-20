import os
import time

import pytest

from onyx.connectors.teams.connector import TeamsConnector
from tests.daily.connectors.utils import load_everything_from_checkpoint_connector
from tests.daily.connectors.utils import to_sections
from tests.daily.connectors.utils import to_text_sections


@pytest.fixture
def teams_credentials() -> dict[str, str]:
    app_id = os.environ["TEAMS_APPLICATION_ID"]
    dir_id = os.environ["TEAMS_DIRECTORY_ID"]
    secret = os.environ["TEAMS_SECRET"]

    return {
        "teams_client_id": app_id,
        "teams_directory_id": dir_id,
        "teams_client_secret": secret,
    }


@pytest.fixture
def teams_connector(
    request: pytest.FixtureRequest,
    teams_credentials: dict[str, str],
) -> TeamsConnector:
    teams: list[str] | None = None
    if hasattr(request, "param"):
        teams = request.param
        if teams is None:
            ...
        elif isinstance(teams, list):
            for name in teams:
                assert isinstance(name, str)
        else:
            raise ValueError(
                f"`request.param` must either be `None` or of type `list[str]`; instead got {type(teams)}"
            )

    teams_connector = TeamsConnector(teams=teams or [])
    teams_connector.load_credentials(teams_credentials)
    return teams_connector


@pytest.mark.parametrize(
    "teams_connector,expected_messages",
    [
        [["Onyx-Testing"], set(["This is the first message in Onyx-Testing ..."])],
        [
            ["Onyx"],
            set(
                [
                    "Hello, world!",
                    "My favorite color is red.\n\xa0\nPablos favorite color is blue",
                    "but not leastyeah!",
                ]
            ),
        ],
    ],
    indirect=["teams_connector"],
)
def test_teams_connector(
    teams_connector: TeamsConnector,
    expected_messages: set[str],
) -> None:
    docs = load_everything_from_checkpoint_connector(
        connector=teams_connector,
        start=0.0,
        end=time.time(),
    )
    actual_messages = set(to_text_sections(to_sections(iter(docs))))
    assert actual_messages == expected_messages
