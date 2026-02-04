import time

import pytest

from onyx.connectors.slack.connector import SlackConnector
from onyx.db.enums import HierarchyNodeType
from tests.daily.connectors.utils import load_all_from_connector
from tests.daily.connectors.utils import to_sections
from tests.daily.connectors.utils import to_text_sections


def test_validate_slack_connector_settings(
    slack_connector: SlackConnector,
) -> None:
    slack_connector.validate_connector_settings()


@pytest.mark.parametrize(
    "slack_connector,expected_messages,expected_channel_name",
    [
        ["general", set(), "general"],
        ["#general", set(), "general"],
        [
            "daily-connector-test-channel",
            set(
                [
                    "Hello, world!",
                    "",
                    "Reply!",
                    "Testing again...",
                ]
            ),
            "daily-connector-test-channel",
        ],
        [
            "#daily-connector-test-channel",
            set(
                [
                    "Hello, world!",
                    "",
                    "Reply!",
                    "Testing again...",
                ]
            ),
            "daily-connector-test-channel",
        ],
    ],
    indirect=["slack_connector"],
)
def test_indexing_channels_with_message_count(
    slack_connector: SlackConnector,
    expected_messages: set[str],
    expected_channel_name: str,
) -> None:
    if not slack_connector.client:
        raise RuntimeError("Web client must be defined")

    result = load_all_from_connector(
        connector=slack_connector,
        start=0.0,
        end=time.time(),
    )
    docs = result.documents
    hierarchy_nodes = result.hierarchy_nodes

    # Verify messages
    actual_messages = set(to_text_sections(to_sections(docs)))
    assert expected_messages == actual_messages

    # Verify hierarchy nodes exist
    assert len(hierarchy_nodes) > 0, "Expected at least one hierarchy node (channel)"

    # Verify all hierarchy nodes are channels with correct structure
    for node in hierarchy_nodes:
        assert node.node_type == HierarchyNodeType.CHANNEL
        assert node.raw_parent_id is None  # Direct child of SOURCE
        assert node.raw_node_id  # Channel ID must be present
        assert node.display_name.startswith("#")  # e.g. "#general"

    # Verify the expected channel appears in the hierarchy nodes
    channel_display_names = {node.display_name for node in hierarchy_nodes}
    assert f"#{expected_channel_name}" in channel_display_names, (
        f"Expected channel '#{expected_channel_name}' not found in hierarchy nodes. "
        f"Found: {channel_display_names}"
    )

    # Verify documents reference their parent channel
    channel_ids = {node.raw_node_id for node in hierarchy_nodes}
    for doc in docs:
        assert (
            doc.parent_hierarchy_raw_node_id is not None
        ), f"Document '{doc.id}' has no parent_hierarchy_raw_node_id"
        assert doc.parent_hierarchy_raw_node_id in channel_ids, (
            f"Document '{doc.id}' has parent_hierarchy_raw_node_id="
            f"'{doc.parent_hierarchy_raw_node_id}' which is not in "
            f"hierarchy nodes: {channel_ids}"
        )


@pytest.mark.parametrize(
    "slack_connector",
    [
        # w/o hashtag
        "doesnt-exist",
        # w/ hashtag
        "#doesnt-exist",
    ],
    indirect=True,
)
def test_indexing_channels_that_dont_exist(
    slack_connector: SlackConnector,
) -> None:
    if not slack_connector.client:
        raise RuntimeError("Web client must be defined")

    with pytest.raises(
        ValueError,
        match=r"Channel '.*' not found in workspace.*",
    ):
        load_all_from_connector(
            connector=slack_connector,
            start=0.0,
            end=time.time(),
        ).documents
