import os
import time

import pytest

from onyx.connectors.discord.connector import DiscordConnector
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentSource
from onyx.connectors.models import HierarchyNode


@pytest.fixture
def discord_connector() -> DiscordConnector:
    connector = DiscordConnector()
    connector.load_credentials(
        {"discord_bot_token": os.environ["DISCORD_CONNECTOR_BOT_TOKEN"]}
    )
    return connector


def test_discord_connector_basic(discord_connector: DiscordConnector) -> None:
    # If there are no Discord messages in the last 7 days, something has gone horribly wrong
    end_time = time.time()
    start_time = end_time - (7 * 24 * 60 * 60)
    doc_batch_generator = discord_connector.poll_source(start_time, end_time)

    doc_batch = next(doc_batch_generator)

    docs: list[Document] = []
    for doc in doc_batch:
        if not isinstance(doc, HierarchyNode):
            docs.append(doc)

    assert len(docs) > 0, "No documents were retrieved from the connector"

    # Check basic document structure
    doc = docs[0]
    assert doc.source == DocumentSource.DISCORD
    assert doc.id is not None
    assert doc.semantic_identifier is not None
    assert len(doc.sections) > 0
    assert doc.sections[0].text is not None
    assert doc.sections[0].link is not None
