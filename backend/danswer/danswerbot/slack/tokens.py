import os
from typing import cast

from danswer.configs.constants import KV_SLACK_BOT_TOKENS_CONFIG_KEY
from danswer.key_value_store.factory import get_kv_store
from danswer.server.manage.models import SlackBotTokens


def fetch_tokens() -> SlackBotTokens:
    # first check env variables
    app_token = os.environ.get("DANSWER_BOT_SLACK_APP_TOKEN")
    bot_token = os.environ.get("DANSWER_BOT_SLACK_BOT_TOKEN")
    if app_token and bot_token:
        return SlackBotTokens(app_token=app_token, bot_token=bot_token)

    dynamic_config_store = get_kv_store()
    return SlackBotTokens(
        **cast(dict, dynamic_config_store.load(key=KV_SLACK_BOT_TOKENS_CONFIG_KEY))
    )


def save_tokens(
    tokens: SlackBotTokens,
) -> None:
    dynamic_config_store = get_kv_store()
    dynamic_config_store.store(
        key=KV_SLACK_BOT_TOKENS_CONFIG_KEY, val=dict(tokens), encrypt=True
    )
