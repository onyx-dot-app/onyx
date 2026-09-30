from pydantic import BaseModel, ConfigDict


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
