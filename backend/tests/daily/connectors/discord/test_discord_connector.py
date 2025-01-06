import os
import time

import pytest

from onyx.connectors.discord.connector import DiscordConnector
from onyx.connectors.models import Document


@pytest.fixture
def discord_connector() -> DiscordConnector:
    server_ids: str | None = os.environ.get("server_ids", None)
    channel_names: str | None = os.environ.get("channel_names", None)

    connector = DiscordConnector(
        server_ids=server_ids.split(",") if server_ids else [],
        channel_names=channel_names.split(",") if channel_names else [],
        start_date=os.environ.get("start_date", None),
    )
    connector.load_credentials(
        {
            "discord_bot_token": os.environ.get("DISCORD_BOT_TOKEN"),
        }
    )
    return connector


@pytest.mark.skip(reason="Test Discord is not setup yet!")
def test_discord_poll_connector(discord_connector: DiscordConnector) -> None:
    end = time.time()
    start = end - 24 * 60 * 60 * 15  # 1 day

    all_docs: list[Document] = []
    channels: set[str] = set()
    threads: set[str] = set()
    for doc_batch in discord_connector.poll_source(start, end):
        for doc in doc_batch:
            if "Channel" in doc.metadata:
                assert isinstance(doc.metadata["Channel"], str)
                channels.add(doc.metadata["Channel"])
            if "Thread" in doc.metadata:
                assert isinstance(doc.metadata["Thread"], str)
                threads.add(doc.metadata["Thread"])
            all_docs.append(doc)

    # might change based on the channels and servers being used
    assert len(all_docs) == 10
    assert len(channels) == 2
    assert len(threads) == 2
