from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict

from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeDirection


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

    base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]


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

    @classmethod
    def classify_scope_change(
        cls,
        old: Self,  # noqa: ARG003
        new: Self,  # noqa: ARG003
    ) -> dict[str, ScopeDirection]:
        """Scope directions for changes the field descriptors cannot express.

        Returns a direction per changed SCOPE field. A returned direction
        replaces the one derived from that field's descriptor. Overrides keep
        the ``Self`` parameters and add
        ``# ty: ignore[invalid-method-override]``: ty rejects ``Self`` in an
        override's parameters, but ``classify_config_change`` only passes
        instances of the overriding class.
        """
        return {}
