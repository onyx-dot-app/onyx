"""A connector config that may be incomplete, validated field by field.

The connector form sends what the admin has filled in so far, and a stored
config may not match its model (rows written before typed configs existed).
``validate_form_state`` checks each field on its own against the connector's
``ConnectorConfig``, so one bad or missing field does not hide the others.
Capability checks read the result through a ``ConfigT`` instance, so their
field access is typed.
"""

from collections.abc import Mapping
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from onyx.connectors.connector_config import ConnectorConfig

ConfigT = TypeVar("ConfigT", bound=ConnectorConfig)


class FormState(BaseModel, Generic[ConfigT]):
    """The validated part of a connector config.

    A field counts as provided when it validated to a value other than None
    or a blank string: the web form sends "" for an empty text input. A field
    that has no default and was not sent is absent from ``config``, so read
    only fields that are provided or have a default.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    config_class: type[ConfigT]
    values: dict[str, Any]
    # Field name to error message, for fields whose value is invalid. Messages
    # never echo the input value.
    errors: dict[str, str]
    # Keys that are not fields of ``config_class``. Kept apart from ``errors``:
    # stored configs written before a field was removed still carry its key.
    unknown: frozenset[str]
    provided: frozenset[str]

    @property
    def config(self) -> ConfigT:
        return self.config_class.model_construct(**self.values)

    @property
    def complete(self) -> ConfigT | None:
        """The full config, with model-level validators run, or None when a
        field is invalid or a required field is missing. Unknown keys do not
        block it; a caller that must reject them checks ``unknown``."""
        if self.errors:
            return None
        try:
            return self.config_class.model_validate(self.values)
        except ValidationError:
            return None

    def missing(self, field_names: frozenset[str]) -> frozenset[str]:
        return field_names - self.provided


def _error_message(error: ValidationError) -> str:
    return "; ".join(str(detail["msg"]) for detail in error.errors())


def validate_form_state(
    config_class: type[ConfigT], raw: Mapping[str, Any]
) -> FormState[ConfigT]:
    """Validates each field of ``raw`` on its own against ``config_class``.

    The field validators of ``config_class`` run, as for a full config. A key
    that is not a field of ``config_class`` goes to ``unknown``.

    ``validate_assignment`` also runs model-level validators, against a
    partial instance. So a ``ConnectorConfig`` must not declare model
    validators (a unit test enforces this); cross-field rules belong in the
    checks.
    """
    scratch = config_class.model_construct()
    validator = config_class.__pydantic_validator__
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}
    unknown: set[str] = set()
    for name, raw_value in raw.items():
        if name not in config_class.model_fields:
            unknown.add(name)
            continue
        try:
            validator.validate_assignment(scratch, name, raw_value)
        except ValidationError as e:
            errors[name] = _error_message(e)
            continue
        # validate_assignment stores the validated value on the instance.
        values[name] = scratch.__dict__[name]
    return FormState(
        config_class=config_class,
        values=values,
        errors=errors,
        unknown=frozenset(unknown),
        provided=frozenset(
            name for name, value in values.items() if not _is_unset(value)
        ),
    )


def _is_unset(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
