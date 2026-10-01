import importlib
import inspect
import typing

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.factory import (
    build_connector_kwargs,
    split_comma_separated_config_fields,
)
from onyx.connectors.registry import CONNECTOR_CLASS_MAP, ConnectorMapping
from onyx.connectors.sharepoint.config import (
    SharepointConnectorConfig,
    SharepointCredentialBinding,
)
from onyx.connectors.web.config import WebConnectorConfig

# (connector class, field) pairs whose model type is intentionally narrower than
# the ``__init__`` annotation, e.g. a str Enum for a closed set of values.
_NARROWED_FIELD_TYPES: set[tuple[str, str]] = {
    ("BlobStorageConnector", "bucket_type"),
    ("ClickupConnector", "connector_type"),
    ("HubSpotConnector", "object_types"),
    ("LocalFileConnector", "file_locations"),
    ("WebConnector", "web_connector_type"),
    ("ZendeskConnector", "content_type"),
    ("ZoomConnector", "rate_limit_percent"),
}


@pytest.mark.parametrize(
    "mapping",
    list(CONNECTOR_CLASS_MAP.values()),
    ids=[source.value for source in CONNECTOR_CLASS_MAP],
)
def test_config_model_matches_connector_init(mapping: ConnectorMapping) -> None:
    connector_class = getattr(  # ods: ignore[getattr]
        importlib.import_module(mapping.module_path), mapping.class_name
    )
    params = inspect.signature(connector_class.__init__).parameters.values()
    named_params = {
        param.name: param
        for param in params
        if param.name != "self"
        and param.kind not in (param.VAR_KEYWORD, param.VAR_POSITIONAL)
    }
    fields = mapping.config_class.model_fields
    type_hints = typing.get_type_hints(connector_class.__init__)

    assert fields.keys() == named_params.keys()
    for name, param in named_params.items():
        field = fields[name]
        if (mapping.class_name, name) not in _NARROWED_FIELD_TYPES:
            assert field.annotation == type_hints[name], name
        if param.default is param.empty:
            assert field.is_required(), name
        else:
            assert not field.is_required(), name
            assert field.get_default(call_default_factory=True) == param.default, name

    accepts_extra_kwargs = any(param.kind == param.VAR_KEYWORD for param in params)
    assert accepts_extra_kwargs == (
        mapping.config_class.model_config.get("extra") == "allow"
    )


def test_build_connector_kwargs_coerces_and_keeps_only_set_keys() -> None:
    kwargs = build_connector_kwargs(
        DocumentSource.MOCK_CONNECTOR,
        {"mock_server_host": "localhost", "mock_server_port": "8001"},
    )

    assert kwargs == {"mock_server_host": "localhost", "mock_server_port": 8001}


def test_build_connector_kwargs_passes_invalid_config_through() -> None:
    invalid_config = {"mock_server_host": "localhost", "unknown_key": True}

    assert (
        build_connector_kwargs(DocumentSource.MOCK_CONNECTOR, invalid_config)
        == invalid_config
    )


def test_credential_binding_class_is_the_most_specific_binding() -> None:
    assert (
        SharepointConnectorConfig.credential_binding_class()
        is SharepointCredentialBinding
    )
    assert WebConnectorConfig.credential_binding_class() is None


@pytest.mark.parametrize(
    "mapping",
    list(CONNECTOR_CLASS_MAP.values()),
    ids=[source.value for source in CONNECTOR_CLASS_MAP],
)
def test_comma_separated_fields_are_config_fields(mapping: ConnectorMapping) -> None:
    config_class = mapping.config_class
    assert config_class.COMMA_SEPARATED_FIELDS <= config_class.model_fields.keys()


def test_comma_separated_fields_are_split_and_stripped() -> None:
    config = {
        "sites": [
            "https://a.sharepoint.com/sites/one, https://a.sharepoint.com/sites/two,",
            " https://a.sharepoint.com/sites/three ",
        ],
        "excluded_paths": ["Archive/a,b.docx"],
    }
    expected_sites = [
        "https://a.sharepoint.com/sites/one",
        "https://a.sharepoint.com/sites/two",
        "https://a.sharepoint.com/sites/three",
    ]

    assert split_comma_separated_config_fields(DocumentSource.SHAREPOINT, config) == {
        "sites": expected_sites,
        "excluded_paths": ["Archive/a,b.docx"],
    }
    assert build_connector_kwargs(DocumentSource.SHAREPOINT, config) == {
        "sites": expected_sites,
        "excluded_paths": ["Archive/a,b.docx"],
    }
