from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, model_validator


class CredentialBinding(BaseModel):
    """The config fields whose valid values depend on the account behind the
    credential, e.g. a site URL, a cloud vs. data center flag, or a national-cloud
    host. A connector config inherits its binding model, so the stored config
    stays flat. Validated on its own from a full config, it ignores the other keys.
    """

    def validate_credential(
        self,
        credential_json: dict[str, Any],  # noqa: ARG002
    ) -> None:
        """Raises ``ConnectorValidationError`` if the credential cannot be used
        with these values. Only checks what the credential itself records; most
        credentials record nothing, so the default accepts every credential."""


class BaseUrlCredentialBinding(CredentialBinding):
    """For sources whose only credential-bound field is the site URL."""

    base_url: str


class ConnectorConfig(BaseModel):
    """Typed shape of a connector's ``connector_specific_config``.

    Each field mirrors one ``__init__`` kwarg of the connector class, with the
    same name, default, and required-ness. ``test_connector_config_models``
    enforces this. Subclasses live in ``<connector>/config.py`` modules, which
    must stay light to import: the registry loads all of them eagerly.
    """

    # extra="forbid" matches the kwargs constructors, where an unknown key is a
    # TypeError. Some configs hold secrets, so errors must not echo input values.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    # List fields where one entry may hold several comma-separated values, so
    # users can paste many values into one input.
    COMMA_SEPARATED_FIELDS: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="before")
    @classmethod
    def _split_comma_separated_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        return cls.split_comma_separated_fields(data)

    @classmethod
    def split_comma_separated_fields(cls, config: dict[str, Any]) -> dict[str, Any]:
        """Returns a copy of ``config`` with each comma-separated field split on
        commas, stripped, and with empty values dropped."""
        result = dict(config)
        for name in cls.COMMA_SEPARATED_FIELDS:
            value = result.get(name)
            if not isinstance(value, list):
                continue
            split_values: list[Any] = []
            for item in value:
                if isinstance(item, str):
                    split_values.extend(
                        part for raw in item.split(",") if (part := raw.strip())
                    )
                else:
                    split_values.append(item)
            result[name] = split_values
        return result

    @classmethod
    def credential_binding_class(cls) -> type[CredentialBinding] | None:
        """The most specific binding model this config inherits, if any."""
        return next(
            (
                base
                for base in cls.__mro__
                if issubclass(base, CredentialBinding)
                and not issubclass(base, ConnectorConfig)
            ),
            None,
        )
