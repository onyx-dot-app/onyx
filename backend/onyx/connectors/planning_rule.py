"""Per-source planning rules for connector config edits.

The default rules classify an edit field by field from the field policies
(see ``field_policy`` and ``config_diff``). A planning rule handles the cases
those policies cannot express, e.g. mode fields that change the meaning of
other fields. A rule is a plain function of the validated old and new config.
It returns None to use the default rules for every field, so it handles only
the special cases. ``planning_rule_registry`` maps each source to its rule.

A rule that needs more than the configs (e.g. the stored files of the file
connector) declares a loader. The caller runs the loader and passes its data
to the rule, so the rule itself stays a pure function.

This module must stay light to import: connector config modules import it.
"""

from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import ScopeDirection

ConfigT = TypeVar("ConfigT", bound=ConnectorConfig)


class PlanningData(BaseModel):
    """Base of the data a rule's loader reads for the rule."""

    model_config = ConfigDict(frozen=True)


DataT = TypeVar("DataT", bound=PlanningData)


class RuleSteps(BaseModel):
    """Propagation a rule decides for some fields in place of the default
    rules. The default rules make no steps for ``field_names``."""

    model_config = ConfigDict(frozen=True)

    field_names: frozenset[str]
    # Config of a one-off backfill over [indexing_start, now]. It names
    # exactly what to index, so the run stays small also on a source that
    # cannot fetch a time window. None when nothing needs indexing.
    backfill_config: dict[str, Any] | None = None
    # Documents that the old config gave and the new config does not.
    prune: bool = False


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
    # The items a change added, per SCOPE field, e.g. for a scoped backfill.
    # Fields not named here use the items from their descriptor.
    added_items: dict[str, list[str]] = {}
    # Steps for the fields it names. Unset: the default rules plan every field.
    rule_steps: RuleSteps | None = None


class PlanningRule(BaseModel):
    """A planning rule bound to the config class it reads. Make one with
    ``planning_rule`` or ``planning_rule_with_data``, which keep the rule
    function strictly typed."""

    model_config = ConfigDict(frozen=True)

    config_class: type[ConnectorConfig]
    apply: Callable[
        [ConnectorConfig, ConnectorConfig, PlanningData | None],
        ConnectorChangeOverride | None,
    ]
    # Reads the rule's data for a pair (by id) and its old and new config.
    load_data: (
        Callable[[Session, int, ConnectorConfig, ConnectorConfig], PlanningData] | None
    ) = None


def _ensure_configs(
    config_class: type[ConfigT], old: ConnectorConfig, new: ConnectorConfig
) -> tuple[ConfigT, ConfigT]:
    if not isinstance(old, config_class) or not isinstance(new, config_class):
        raise TypeError(
            f"The planning rule for {config_class.__name__} got "
            f"{type(old).__name__} and {type(new).__name__}"
        )
    return old, new


def planning_rule(
    config_class: type[ConfigT],
    rule: Callable[[ConfigT, ConfigT], ConnectorChangeOverride | None],
) -> PlanningRule:
    def apply(
        old: ConnectorConfig,
        new: ConnectorConfig,
        data: PlanningData | None,  # noqa: ARG001
    ) -> ConnectorChangeOverride | None:
        return rule(*_ensure_configs(config_class, old, new))

    return PlanningRule(config_class=config_class, apply=apply)


def planning_rule_with_data(
    config_class: type[ConfigT],
    data_class: type[DataT],
    load_data: Callable[[Session, int, ConfigT, ConfigT], DataT],
    rule: Callable[[ConfigT, ConfigT, DataT], ConnectorChangeOverride | None],
) -> PlanningRule:
    """A rule that also reads what ``load_data`` returns. Without its data
    (e.g. the caller has no DB session) the default rules apply."""

    def apply(
        old: ConnectorConfig, new: ConnectorConfig, data: PlanningData | None
    ) -> ConnectorChangeOverride | None:
        typed_old, typed_new = _ensure_configs(config_class, old, new)
        if data is None:
            return None
        if not isinstance(data, data_class):
            raise TypeError(
                f"The planning rule for {config_class.__name__} got "
                f"{type(data).__name__}, not {data_class.__name__}"
            )
        return rule(typed_old, typed_new, data)

    def load(
        db_session: Session, cc_pair_id: int, old: ConnectorConfig, new: ConnectorConfig
    ) -> PlanningData:
        return load_data(
            db_session, cc_pair_id, *_ensure_configs(config_class, old, new)
        )

    return PlanningRule(config_class=config_class, apply=apply, load_data=load)
