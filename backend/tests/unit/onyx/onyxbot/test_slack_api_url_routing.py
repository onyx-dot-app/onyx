"""The bot's Web API client, and so its Socket Mode handshake, use SLACK_API_URL.

Socket Mode has no host setting of its own: the SDK opens the socket by calling
apps.connections.open on the web client. So routing the web client is what
moves the socket to GovSlack.
"""

from unittest.mock import patch

from onyx.onyxbot.slack.listener import _get_socket_client
from onyx.server.manage.models import SlackBotTokens

_LISTENER = "onyx.onyxbot.slack.listener"
_TOKENS = SlackBotTokens(bot_token="xoxb-test", app_token="xapp-test")


def test_web_client_uses_configured_base_url() -> None:
    with patch(f"{_LISTENER}.SLACK_API_URL", "https://slack-gov.com/api/"):
        client = _get_socket_client(_TOKENS, tenant_id="public", slack_bot_id=1)
    assert client.web_client.base_url == "https://slack-gov.com/api/"


def test_socket_handshake_goes_to_configured_host() -> None:
    with patch(f"{_LISTENER}.SLACK_API_URL", "https://slack-gov.com/api/"):
        client = _get_socket_client(_TOKENS, tenant_id="public", slack_bot_id=1)
    with patch.object(
        client.web_client, "api_call", return_value={"ok": True, "url": "wss://x"}
    ) as api_call:
        client.issue_new_wss_url()
    api_call.assert_called_once()
    assert api_call.call_args.args[0] == "apps.connections.open"
    assert client.web_client.base_url == "https://slack-gov.com/api/"


def test_default_is_commercial_slack() -> None:
    client = _get_socket_client(_TOKENS, tenant_id="public", slack_bot_id=1)
    assert client.web_client.base_url == "https://slack.com/api/"
