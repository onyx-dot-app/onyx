import time

import pytest

from onyx.connectors.slack.connector import SlackConnector
from tests.daily.connectors.utils import load_everything_from_checkpoint_connector
from tests.daily.connectors.utils import to_sections
from tests.daily.connectors.utils import to_text_sections


def test_validate_slack_connector_settings(
    slack_connector: SlackConnector,
) -> None:
    slack_connector.validate_connector_settings()


@pytest.mark.parametrize(
    "slack_connector,expected_messages",
    [
        ["general", set()],
        ["#general", set()],
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
        ],
    ],
    indirect=["slack_connector"],
)
def test_indexing_channels_with_message_count(
    slack_connector: SlackConnector,
    expected_messages: set[str],
) -> None:
    if not slack_connector.client:
        raise RuntimeError("Web client must be defined")

    docs = load_everything_from_checkpoint_connector(
        connector=slack_connector,
        start=0.0,
        end=time.time(),
    )

    actual_messages = set(to_text_sections(to_sections(iter(docs))))
    assert expected_messages == actual_messages


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
        load_everything_from_checkpoint_connector(
            connector=slack_connector,
            start=0.0,
            end=time.time(),
        )
