import os
import time

import pytest

from danswer.connectors.discord.connector import DiscordConnector
from danswer.connectors.models import Document


@pytest.fixture
def discord_connector() -> DiscordConnector:
    server_ids: str | None = os.environ.get("server_ids", None)
    channel_names: str | None = os.environ.get("channel_names", None)

    connector = DiscordConnector(
        server_ids=server_ids.split(",") if server_ids else None,
        channel_names=channel_names.split(",") if channel_names else None,
        start_date=os.environ.get("start_date", None),
    )
    connector.load_credentials(
        {
            "discord_bot_token": os.environ.get("discord_bot_token"),
        }
    )
    return connector


def test_discord_poll_connector(discord_connector: DiscordConnector) -> None:
    end = time.time()
    start = end - 24 * 60 * 60 * 15  # 1 day

    all_docs: list[Document] = []
    channels: set[str] = set()
    threads: set[str] = set()
    for doc_batch in discord_connector.poll_source(start, end):
        for doc in doc_batch:
            if "Channel" in doc.metadata:
                channels.add(doc.metadata["Channel"])
            if "Thread" in doc.metadata:
                threads.add(doc.metadata["Thread"])
            all_docs.append(doc)

    assert (
        len(all_docs) == 10
    )  # might change based on the channels and servers being used

    assert (
        len(channels) == 2
    )  # might change based on the channels and servers being used
    assert (
        len(threads) == 2
    )  # might change based on the channels and servers being used
