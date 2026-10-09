from typing import Annotated, Self

from onyx.configs.app_configs import INDEX_BATCH_SIZE, SLACK_NUM_THREADS
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeExclude,
    ScopeInclude,
    ScopeOpaque,
    ScopeToggle,
)

_COSMETIC = FieldPolicy(FieldClass.COSMETIC)
_INCLUDE_BOT_MESSAGES = "include_bot_messages"


class SlackConnectorConfig(ConnectorConfig):
    # A pattern list in regex mode still widens when a pattern is added.
    channels: Annotated[
        list[str] | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=("channel_regex_enabled",),
        ),
    ] = None
    channel_regex_enabled: Annotated[
        bool, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
    ] = False
    exclude_channels: Annotated[
        list[str] | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeExclude(),
            depends_on=("exclude_channel_regex_enabled",),
        ),
    ] = None
    exclude_channel_regex_enabled: Annotated[
        bool, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
    ] = False
    include_bot_messages: Annotated[
        bool, FieldPolicy(FieldClass.SCOPE, scope=ScopeToggle(widens_when=True))
    ] = False
    batch_size: Annotated[int, _COSMETIC] = INDEX_BATCH_SIZE
    num_threads: Annotated[int, _COSMETIC] = SLACK_NUM_THREADS
    use_redis: Annotated[bool, _COSMETIC] = True

    @classmethod
    def classify_scope_change(  # ty: ignore[invalid-method-override]
        cls, old: Self, new: Self
    ) -> dict[str, ScopeDirection]:
        # Bot messages are also part of thread documents with human messages.
        # Turning them off drops bot-only threads (prune) and changes mixed
        # threads, which only a from-beginning run rewrites.
        if old.include_bot_messages and not new.include_bot_messages:
            return {_INCLUDE_BOT_MESSAGES: ScopeDirection.BOTH}
        return {}
