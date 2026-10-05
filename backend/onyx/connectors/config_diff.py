"""Classifies a connector config edit field by field, using the field policies
declared on the typed config models (see ``field_policy``) and the source's
planning rule, if it has one (see ``planning_rule``)."""

from typing import Any

import pydantic
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeExclude,
    ScopeInclude,
    ScopeOpaque,
    ScopeOrdered,
    ScopeToggle,
    get_field_policy,
)
from onyx.connectors.planning_rule import (
    ConnectorChangeOverride,
    PlanningData,
    PlanningRule,
)
from onyx.connectors.planning_rule_registry import PLANNING_RULES
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.utils.logger import setup_logger

logger = setup_logger()

ITEM_SEPARATOR = ","


class ConfigFieldChange(BaseModel):
    field_name: str
    field_class: FieldClass
    # NONE for fields that are not SCOPE.
    scope_direction: ScopeDirection = ScopeDirection.NONE
    # Set only for ScopeInclude and ScopeExclude fields.
    added_items: list[str] = []
    removed_items: list[str] = []


class FieldPolicyGaps(BaseModel):
    fields_without_policy: list[str]
    scope_fields_without_descriptor: list[str]


class _ScopeChange(BaseModel):
    direction: ScopeDirection
    added_items: list[str] = []
    removed_items: list[str] = []


def _to_items(value: Any, split_on_commas: bool) -> list[str] | None:
    """Normalizes a list, None, or string into unique items, in order. A
    string is one item unless ``split_on_commas``. None for any other type.

    List entries are kept exactly, since connectors (e.g. Slack) match them
    exactly. Only the pieces of a string are stripped, and blank pieces are
    dropped.
    """
    if value is None:
        return []
    if isinstance(value, str):
        raw_pieces = value.split(ITEM_SEPARATOR) if split_on_commas else [value]
        pieces = (piece.strip() for piece in raw_pieces)
        return list(dict.fromkeys(piece for piece in pieces if piece))
    if isinstance(value, list):
        return list(dict.fromkeys(str(item) for item in value))
    return None


def _include_means_all(value: Any) -> bool:
    """For ``empty_list_means_none`` fields: only None or a blank string
    fetches everything."""
    return value is None or (isinstance(value, str) and not value.strip())


def _item_direction(added: list[str], removed: list[str]) -> ScopeDirection:
    if added and removed:
        return ScopeDirection.BOTH
    if added:
        return ScopeDirection.WIDEN
    if removed:
        return ScopeDirection.NARROW
    return ScopeDirection.NONE


def _inverted(direction: ScopeDirection) -> ScopeDirection:
    if direction == ScopeDirection.WIDEN:
        return ScopeDirection.NARROW
    if direction == ScopeDirection.NARROW:
        return ScopeDirection.WIDEN
    return direction


def _ordered_direction(
    field_name: str, scope: ScopeOrdered, old_value: Any, new_value: Any
) -> ScopeDirection:
    old: Any = scope.none_means if old_value is None else old_value
    new: Any = scope.none_means if new_value is None else new_value
    if old == new or (old in scope.unbounded and new in scope.unbounded):
        return ScopeDirection.NONE
    if old in scope.unbounded:
        return ScopeDirection.NARROW
    if new in scope.unbounded:
        return ScopeDirection.WIDEN
    try:
        larger = new > old
    except TypeError:
        logger.warning(
            "Ordered scope field %s has values that do not compare", field_name
        )
        return ScopeDirection.UNKNOWN
    return (
        ScopeDirection.WIDEN
        if larger == scope.widens_when_larger
        else ScopeDirection.NARROW
    )


def _scope_change(
    field_name: str, policy: FieldPolicy, old_value: Any, new_value: Any
) -> _ScopeChange:
    scope = policy.scope
    if scope is None or isinstance(scope, ScopeOpaque):
        return _ScopeChange(direction=ScopeDirection.UNKNOWN)

    if isinstance(scope, ScopeOrdered):
        return _ScopeChange(
            direction=_ordered_direction(field_name, scope, old_value, new_value)
        )

    if isinstance(scope, ScopeToggle):
        if not isinstance(old_value, bool) or not isinstance(new_value, bool):
            logger.warning("Scope toggle %s is not a bool", field_name)
            return _ScopeChange(direction=ScopeDirection.UNKNOWN)
        if old_value == new_value:
            return _ScopeChange(direction=ScopeDirection.NONE)
        return _ScopeChange(
            direction=(
                ScopeDirection.WIDEN
                if new_value == scope.widens_when
                else ScopeDirection.NARROW
            )
        )

    old_items = _to_items(old_value, scope.split_on_commas)
    new_items = _to_items(new_value, scope.split_on_commas)
    if old_items is None or new_items is None:
        logger.warning("Scope field %s is not a list, a string, or None", field_name)
        return _ScopeChange(direction=ScopeDirection.UNKNOWN)
    old_set = set(old_items)
    new_set = set(new_items)
    added = [item for item in new_items if item not in old_set]
    removed = [item for item in old_items if item not in new_set]

    if isinstance(scope, ScopeExclude):
        direction = _inverted(_item_direction(added, removed))
    elif scope.empty_list_means_none:
        old_all = _include_means_all(old_value)
        new_all = _include_means_all(new_value)
        if old_all == new_all:
            direction = _item_direction(added, removed)
        else:
            direction = ScopeDirection.WIDEN if new_all else ScopeDirection.NARROW
    elif scope.empty_means_all and not old_items and new_items:
        direction = ScopeDirection.NARROW
    elif scope.empty_means_all and old_items and not new_items:
        direction = ScopeDirection.WIDEN
    else:
        direction = _item_direction(added, removed)
    return _ScopeChange(direction=direction, added_items=added, removed_items=removed)


def _with_defaults(
    config_class: type[ConnectorConfig], config: dict[str, Any]
) -> dict[str, Any]:
    defaults = {
        name: field.get_default(call_default_factory=True)
        for name, field in config_class.model_fields.items()
        if not field.is_required()
    }
    return defaults | config


def _policy_for(config_class: type[ConnectorConfig], name: str) -> FieldPolicy | None:
    field_info = config_class.model_fields.get(name)
    return get_field_policy(field_info) if field_info else None


def _validate(
    config_class: type[ConnectorConfig], config: dict[str, Any]
) -> ConnectorConfig | None:
    try:
        return config_class.model_validate(config)
    except pydantic.ValidationError as e:
        # Rows written before typed configs existed may not conform.
        logger.warning(
            "Connector config does not match %s: errors=%s",
            config_class.__name__,
            e,
        )
        return None


def classify_source_config_change(
    source: DocumentSource,
    old_config: dict[str, Any],
    new_config: dict[str, Any],
    rule_data: PlanningData | None = None,
) -> list[ConfigFieldChange]:
    """``classify_config_change`` with the source's config class and planning
    rule."""
    return classify_config_change(
        CONNECTOR_CLASS_MAP[source].config_class,
        old_config,
        new_config,
        PLANNING_RULES.get(source),
        rule_data,
    )


def source_change_override(
    source: DocumentSource,
    old_config: dict[str, Any],
    new_config: dict[str, Any],
    rule_data: PlanningData | None = None,
) -> ConnectorChangeOverride | None:
    """What the source's planning rule decides for the edit. None when the
    source has no rule, the rule uses the default rules, or either config
    fails validation."""
    rule = PLANNING_RULES.get(source)
    if rule is None:
        return None
    config_class = CONNECTOR_CLASS_MAP[source].config_class
    old_model = _validate(config_class, old_config)
    new_model = _validate(config_class, new_config)
    if old_model is None or new_model is None:
        return None
    override = rule.apply(old_model, new_model, rule_data)
    if override is not None and override.rule_steps is not None:
        unknown_fields = override.rule_steps.field_names - set(
            config_class.model_fields
        )
        if unknown_fields:
            raise ValueError(
                f"The planning rule for {config_class.__name__} returned steps "
                f"for unknown fields: {sorted(unknown_fields)}"
            )
    return override


def load_source_rule_data(
    db_session: Session,
    source: DocumentSource,
    cc_pair_id: int,
    old_config: dict[str, Any],
    new_config: dict[str, Any],
) -> PlanningData | None:
    """The data the source's planning rule reads for this edit. None when the
    rule reads none or either config fails validation (the rule is then
    skipped)."""
    rule = PLANNING_RULES.get(source)
    if rule is None or rule.load_data is None:
        return None
    config_class = CONNECTOR_CLASS_MAP[source].config_class
    old_model = _validate(config_class, old_config)
    new_model = _validate(config_class, new_config)
    if old_model is None or new_model is None:
        return None
    return rule.load_data(db_session, cc_pair_id, old_model, new_model)


def classify_config_change(
    config_class: type[ConnectorConfig],
    old_config: dict[str, Any],
    new_config: dict[str, Any],
    rule: PlanningRule | None = None,
    rule_data: PlanningData | None = None,
) -> list[ConfigFieldChange]:
    """One entry per field whose value differs between the two configs.

    Configs are compared as validated models, so defaults and coercion do not
    show as changes. If either config fails validation, raw values (with field
    defaults filled in) are compared and ``rule`` is skipped. A field with no
    policy counts as BEHAVIOR. A SCOPE change with no effect on scope (e.g.
    reordered items) is left out. A direction from ``rule`` replaces the one
    derived from the field's descriptor.
    """
    old_model = _validate(config_class, old_config)
    new_model = _validate(config_class, new_config)
    override: ConnectorChangeOverride | None = None
    if old_model and new_model:
        old_values = old_model.model_dump(mode="json")
        new_values = new_model.model_dump(mode="json")
        if rule:
            override = rule.apply(old_model, new_model, rule_data)
    else:
        old_values = _with_defaults(config_class, old_config)
        new_values = _with_defaults(config_class, new_config)
    rule_directions = override.scope_directions if override else {}
    rule_added_items = override.added_items if override else {}
    for name in [*rule_directions, *rule_added_items]:
        policy = _policy_for(config_class, name)
        if policy is None or policy.field_class != FieldClass.SCOPE:
            raise ValueError(
                f"The planning rule for {config_class.__name__} returned {name}, which is not a SCOPE field"
            )

    changed_names = [
        name
        for name in dict.fromkeys([*old_values, *new_values])
        if old_values.get(name) != new_values.get(name)
    ]
    changed_name_set = set(changed_names)
    changes: list[ConfigFieldChange] = []
    for name in changed_names:
        policy = _policy_for(config_class, name)
        if policy is None:
            changes.append(
                ConfigFieldChange(field_name=name, field_class=FieldClass.BEHAVIOR)
            )
            continue
        if policy.field_class != FieldClass.SCOPE:
            changes.append(
                ConfigFieldChange(field_name=name, field_class=policy.field_class)
            )
            continue

        scope_change = _scope_change(
            name, policy, old_values.get(name), new_values.get(name)
        )
        direction = scope_change.direction
        if direction != ScopeDirection.NONE and any(
            dependency in changed_name_set for dependency in policy.depends_on
        ):
            direction = ScopeDirection.UNKNOWN
        direction = rule_directions.get(name, direction)
        if direction == ScopeDirection.NONE:
            continue
        changes.append(
            ConfigFieldChange(
                field_name=name,
                field_class=FieldClass.SCOPE,
                scope_direction=direction,
                added_items=rule_added_items.get(name, scope_change.added_items),
                removed_items=scope_change.removed_items,
            )
        )

    return changes


def build_source_scoped_backfill_config(
    source: DocumentSource,
    old_config: dict[str, Any],
    new_config: dict[str, Any],
    rule_data: PlanningData | None = None,
) -> dict[str, Any] | None:
    """``build_scoped_backfill_config`` with the source's config class and
    planning rule."""
    return build_scoped_backfill_config(
        CONNECTOR_CLASS_MAP[source].config_class,
        old_config,
        new_config,
        PLANNING_RULES.get(source),
        rule_data,
    )


def build_scoped_backfill_config(
    config_class: type[ConnectorConfig],
    old_config: dict[str, Any],
    new_config: dict[str, Any],
    rule: PlanningRule | None = None,
    rule_data: PlanningData | None = None,
) -> dict[str, Any] | None:
    """The new config limited to the items a widening added, for a one-off
    backfill of just those items.

    Returns None unless exactly one non-COSMETIC change widens a ScopeInclude
    field by adding items. With two widened include fields, a document must
    match both, so the added items of each would miss pairs of old and new
    items. An include field that goes from items to "all" widens to
    everything, which no delta can express.
    """
    changes = [
        change
        for change in classify_config_change(
            config_class, old_config, new_config, rule, rule_data
        )
        if change.field_class != FieldClass.COSMETIC
    ]
    if len(changes) != 1:
        return None
    change = changes[0]
    if (
        change.field_class != FieldClass.SCOPE
        or change.scope_direction != ScopeDirection.WIDEN
        or not change.added_items
    ):
        return None
    policy = _policy_for(config_class, change.field_name)
    if policy is None or not isinstance(policy.scope, ScopeInclude):
        return None

    delta_config = dict(new_config)
    new_value = new_config.get(change.field_name)
    if isinstance(new_value, str):
        # A one-item string keeps its exact value.
        delta_config[change.field_name] = (
            ITEM_SEPARATOR.join(change.added_items)
            if policy.scope.split_on_commas
            else new_value
        )
    else:
        delta_config[change.field_name] = change.added_items

    if _validate(config_class, delta_config) is None:
        return None
    return delta_config


def find_field_policy_gaps(config_class: type[ConnectorConfig]) -> FieldPolicyGaps:
    fields_without_policy: list[str] = []
    scope_fields_without_descriptor: list[str] = []
    for name, field_info in config_class.model_fields.items():
        policy = get_field_policy(field_info)
        if policy is None:
            fields_without_policy.append(name)
        elif policy.field_class == FieldClass.SCOPE and policy.scope is None:
            scope_fields_without_descriptor.append(name)
    return FieldPolicyGaps(
        fields_without_policy=fields_without_policy,
        scope_fields_without_descriptor=scope_fields_without_descriptor,
    )


def build_field_policy_report() -> dict[DocumentSource, FieldPolicyGaps]:
    """The policy gaps of each registered source that has any."""
    report: dict[DocumentSource, FieldPolicyGaps] = {}
    for source, mapping in CONNECTOR_CLASS_MAP.items():
        gaps = find_field_policy_gaps(mapping.config_class)
        if gaps.fields_without_policy or gaps.scope_fields_without_descriptor:
            report[source] = gaps
    return report
