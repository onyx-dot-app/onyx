"""Per-source planning rules for connector config edits.

The default rules classify an edit field by field from the field policies
(see ``field_policy`` and ``config_diff``). A planning rule handles the cases
those policies cannot express, e.g. mode fields that change the meaning of
other fields. A rule is a plain function of the validated old and new config.
It returns None to use the default rules for every field, so it handles only
the special cases. ``planning_rule_registry`` maps each source to its rule.

This module must stay light to import: connector config modules import it.
"""

from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ConfigDict

from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import ScopeDirection

ConfigT = TypeVar("ConfigT", bound=ConnectorConfig)


class ConnectorChangeOverride(BaseModel):
    """What a planning rule decides in place of the default rules.

    Each field covers one part of the plan, and its default leaves that part
    to the default rules. New fields must keep this property, so that
    existing rules do not change when a field is added.
    """

    model_config = ConfigDict(frozen=True)

    # A direction per SCOPE field. Fields not named here use the direction
    # from their descriptor.
    scope_directions: dict[str, ScopeDirection] = {}


class PlanningRule(BaseModel):
    """A planning rule bound to the config class it reads. Make one with
    ``planning_rule``, which keeps the rule function strictly typed."""

    model_config = ConfigDict(frozen=True)

    config_class: type[ConnectorConfig]
    apply: Callable[[ConnectorConfig, ConnectorConfig], ConnectorChangeOverride | None]


def planning_rule(
    config_class: type[ConfigT],
    rule: Callable[[ConfigT, ConfigT], ConnectorChangeOverride | None],
) -> PlanningRule:
    def apply(
        old: ConnectorConfig, new: ConnectorConfig
    ) -> ConnectorChangeOverride | None:
        if not isinstance(old, config_class) or not isinstance(new, config_class):
            raise TypeError(
                f"The planning rule for {config_class.__name__} got "
                f"{type(old).__name__} and {type(new).__name__}"
            )
        return rule(old, new)

    return PlanningRule(config_class=config_class, apply=apply)
