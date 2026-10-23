from pydantic import field_validator

from onyx.connectors.capability_checks.form_state import validate_form_state
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.registry import CONNECTOR_CLASS_MAP


class _SiteConfig(ConnectorConfig):
    base_url: str
    spaces: list[str] | None = None
    include_archived: bool = False
    batch_size: int = 16

    @field_validator("base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("must start with https://")
        return value.rstrip("/")


def test_each_field_is_validated_on_its_own() -> None:
    form_state = validate_form_state(
        _SiteConfig,
        {"spaces": ["eng"], "batch_size": "not-a-number", "include_archived": True},
    )

    assert form_state.values == {"spaces": ["eng"], "include_archived": True}
    assert set(form_state.errors) == {"batch_size"}
    assert form_state.provided == {"spaces", "include_archived"}
    assert form_state.missing(frozenset({"spaces", "base_url"})) == {"base_url"}


def test_field_validators_run_and_messages_hide_the_input() -> None:
    form_state = validate_form_state(_SiteConfig, {"base_url": "http://secret-host"})

    assert "must start with https://" in form_state.errors["base_url"]
    assert "secret-host" not in form_state.errors["base_url"]
    assert validate_form_state(
        _SiteConfig, {"base_url": "https://acme.example.com/"}
    ).values == {"base_url": "https://acme.example.com"}


def test_unknown_keys_are_kept_apart_from_errors() -> None:
    form_state = validate_form_state(
        _SiteConfig, {"base_url": "https://acme.example.com", "legacy_key": 1}
    )

    assert form_state.unknown == {"legacy_key"}
    assert form_state.errors == {}
    assert form_state.complete is not None


def test_none_is_not_provided() -> None:
    form_state = validate_form_state(_SiteConfig, {"spaces": None})

    assert form_state.provided == frozenset()


class _ScopeConfig(ConnectorConfig):
    space: str = ""
    page_id: str = ""


def test_blank_string_is_not_provided_but_keeps_its_value() -> None:
    form_state = validate_form_state(_ScopeConfig, {"space": " ", "page_id": "42"})

    assert form_state.provided == {"page_id"}
    assert form_state.config.space == " "


def test_config_is_typed_with_defaults_for_the_rest() -> None:
    config = validate_form_state(_SiteConfig, {"spaces": ["eng"]}).config

    assert isinstance(config, _SiteConfig)
    assert config.spaces == ["eng"]
    assert config.batch_size == 16


def test_complete_needs_every_required_field_and_no_errors() -> None:
    assert validate_form_state(_SiteConfig, {"spaces": ["eng"]}).complete is None
    assert (
        validate_form_state(
            _SiteConfig, {"base_url": "https://acme.example.com", "batch_size": "x"}
        ).complete
        is None
    )
    complete = validate_form_state(
        _SiteConfig, {"base_url": "https://acme.example.com"}
    ).complete
    assert complete == _SiteConfig(base_url="https://acme.example.com")


def test_no_connector_config_declares_model_validators() -> None:
    """validate_form_state validates fields one at a time, and pydantic runs
    model validators on each assignment against a partial instance."""
    with_model_validators = sorted(
        source.value
        for source, mapping in CONNECTOR_CLASS_MAP.items()
        if mapping.config_class.__pydantic_decorators__.model_validators
    )

    assert with_model_validators == []
