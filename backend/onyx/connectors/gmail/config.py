from typing import Annotated, Any

from pydantic import field_validator

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig, field_format_error
from onyx.connectors.field_policy import FieldClass, FieldPolicy
from onyx.connectors.planning_rule import ConnectorChangeOverride, RuleSteps

_COLLABORATIVE_INBOX_GROUPS = "collaborative_inbox_groups"


class GmailConnectorConfig(ConnectorConfig):
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    # Addresses of Google Groups with Collaborative Inbox turned on. The mail
    # they deliver is indexed once for the group, not once per member.
    collaborative_inbox_groups: Annotated[
        list[str] | None, FieldPolicy(FieldClass.BEHAVIOR)
    ] = None

    # Normalized so that a reorder or a case change is not a config change.
    @field_validator("collaborative_inbox_groups", mode="before")
    @classmethod
    def _normalize_collaborative_inbox_groups(cls, value: Any) -> Any:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return value
        return sorted({entry.strip().lower() for entry in value if entry.strip()})

    @field_validator("collaborative_inbox_groups")
    @classmethod
    def _collaborative_inbox_groups_are_addresses(
        cls, value: list[str] | None
    ) -> list[str] | None:
        if any(entry.count("@") != 1 for entry in value or []):
            raise field_format_error(
                "Enter each group as an email address, such as support@example.com."
            )
        return value


def gmail_planning_rule(
    old: GmailConnectorConfig, new: GmailConnectorConfig
) -> ConnectorChangeOverride | None:
    # By design, an added group applies to mail indexed from then on. Older mail
    # stays in its owner-only thread documents: a re-index reads every mailbox,
    # so the admin starts it. A removed group keeps the default full re-index.
    old_groups = set(old.collaborative_inbox_groups or [])
    new_groups = set(new.collaborative_inbox_groups or [])
    if old_groups == new_groups or old_groups - new_groups:
        return None
    return ConnectorChangeOverride(
        rule_steps=RuleSteps(field_names=frozenset({_COLLABORATIVE_INBOX_GROUPS}))
    )
