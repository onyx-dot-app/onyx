import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from onyx.connectors.discord.connector import DiscordConnector
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentSource


def load_test_data(file_name: str = "test_discord_data.json") -> dict[str, Any]:
    current_dir = Path(__file__).parent
    with open(current_dir / file_name, "r") as f:
        return json.load(f)


@pytest.fixture
def discord_connector() -> DiscordConnector:
    connector = DiscordConnector()
    connector.load_credentials({"discord_bot_token": os.environ["DISCORD_BOT_TOKEN"]})
    return connector


@pytest.mark.xfail(
    reason="Environment variable not set for some reason",
)
def test_discord_connector_basic(discord_connector: DiscordConnector) -> None:
    test_data = load_test_data()

    target_doc_id = test_data["target_doc"]["id"]
    target_doc: Document | None = None

    all_docs: list[Document] = []
    channels: set[str] = set()
    threads: set[str] = set()

    for doc_batch in discord_connector.poll_source(0, time.time()):
        for doc in doc_batch:
            if "Channel" in doc.metadata:
                assert isinstance(doc.metadata["Channel"], str)
                channels.add(doc.metadata["Channel"])
            if "Thread" in doc.metadata:
                assert isinstance(doc.metadata["Thread"], str)
                threads.add(doc.metadata["Thread"])
            if doc.id == target_doc_id:
                target_doc = doc
            all_docs.append(doc)

    # Check all docs are returned, with the correct number of channels and threads
    assert len(all_docs) == 8
    assert len(channels) == 2
    assert len(threads) == 1

    # Check that all the channels and threads are returned
    assert channels == set(test_data["channels"])
    assert threads == set(test_data["threads"])

    # Check the target doc
    assert target_doc is not None
    assert target_doc.id == target_doc_id
    assert target_doc.source == DocumentSource.DISCORD
    assert target_doc.metadata["Thread"] == test_data["target_doc"]["Thread"]
    assert target_doc.sections[0].link == test_data["target_doc"]["link"]
    assert target_doc.sections[0].text == test_data["target_doc"]["text"]
    assert (
        target_doc.semantic_identifier == test_data["target_doc"]["semantic_identifier"]
    )

    # Ensure all the docs section data is returned correctly
    assert {doc.sections[0].text for doc in all_docs} == set(test_data["texts"])
    assert {doc.sections[0].link for doc in all_docs} == set(test_data["links"])
