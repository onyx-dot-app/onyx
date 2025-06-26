import os
import time
from dataclasses import dataclass

import pytest

from onyx.connectors.models import Document
from onyx.connectors.teams.connector import TeamsConnector
from tests.daily.connectors.utils import load_everything_from_checkpoint_connector
from tests.daily.connectors.utils import to_documents


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
    teams_credentials: dict[str, str],
) -> TeamsConnector:
    teams_connector = TeamsConnector(teams=["Onyx-Testing"])
    teams_connector.load_credentials(teams_credentials)
    return teams_connector


@dataclass
class TeamsThread:
    thread: str
    member_emails: set[str]
    is_public: bool


def _doc_to_teams_thread(doc: Document) -> TeamsThread:
    assert (
        doc.external_access
    ), f"ExternalAccess should always be available, instead got {doc=}"

    return TeamsThread(
        thread=doc.get_text_content(),
        member_emails=doc.external_access.external_user_emails,
        is_public=doc.external_access.is_public,
    )


def _build_map(threads: list[TeamsThread]) -> dict[str, TeamsThread]:
    map: dict[str, TeamsThread] = {}

    for thread in threads:
        assert thread.thread not in map, ""
        map[thread.thread] = thread

    return map


@pytest.mark.parametrize(
    "expected_docs",
    [
        [
            # Posted in "Public Channel"
            TeamsThread(
                thread="This is the first message in Onyx-Testing ...This is a reply!This is a second reply.Third.4th.5",
                member_emails=set(["test@danswerai.onmicrosoft.com"]),
                is_public=True,
            ),
            TeamsThread(
                thread="Testing body.",
                member_emails=set(["test@danswerai.onmicrosoft.com"]),
                is_public=True,
            ),
            TeamsThread(
                thread="Hello, world! Nice to meet you all.",
                member_emails=set(["raunak@onyx.app"]),
                is_public=True,
            ),
            # Posted in "Private Channel (Raunak is excluded)"
            TeamsThread(
                thread="This is a test post. Raunak should not be able to see this!",
                member_emails=set(["test@danswerai.onmicrosoft.com"]),
                is_public=False,
            ),
            # Posted in "Private Channel (Raunak is a member)"
            TeamsThread(
                thread="This is a test post in a private channel that Raunak does have access to! Hello, Raunak!"
                "Hello, world! I am just a member in this chat, but not an owner.",
                member_emails=set(
                    ["test@danswerai.onmicrosoft.com", "raunak@onyx.app"]
                ),
                is_public=False,
            ),
            # Posted in "Private Channel (Raunak owns)"
            TeamsThread(
                thread="This is a test post in a private channel that Raunak is an owner of! Whoa!"
                "Hello, world! I am an owner of this chat. The power!",
                member_emails=set(
                    ["test@danswerai.onmicrosoft.com", "raunak@onyx.app"]
                ),
                is_public=False,
            ),
        ],
    ],
)
def test_teams_connector(
    teams_connector: TeamsConnector,
    expected_docs: list[TeamsThread],
) -> None:
    docs_iter = load_everything_from_checkpoint_connector(
        connector=teams_connector,
        start=0.0,
        end=time.time(),
    )

    actual_docs = [
        _doc_to_teams_thread(doc=doc) for doc in to_documents(iterator=iter(docs_iter))
    ]

    actual_docs_map = _build_map(threads=actual_docs)
    expected_docs_map = _build_map(threads=expected_docs)

    assert actual_docs_map == expected_docs_map
