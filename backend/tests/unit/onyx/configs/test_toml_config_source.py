"""Unit tests for the TOML settings source in shared_configs.settings_base.

Uses a synthetic settings class so the tests are independent of any real
config module's schema.
"""

from enum import Enum
from pathlib import Path

import pytest
from pydantic import AliasChoices, Field

from shared_configs.settings_base import (
    ONYX_CONFIG_FILE_DISABLED,
    ONYX_CONFIG_FILE_ENV_VAR,
    CommaSeparatedStrList,
    LegacyEnvBool,
    LegacyEnvBoolUnlessFalse,
    OnyxBaseSettings,
    clear_toml_document_cache,
)


class _DemoColor(str, Enum):
    RED = "red"
    BLUE = "blue"


class _DemoSettings(OnyxBaseSettings):
    demo_host: str = Field(
        default="localhost", json_schema_extra={"toml_path": "demo.host"}
    )
    demo_port: int = Field(default=8080, json_schema_extra={"toml_path": "demo.port"})
    demo_flag: LegacyEnvBool = Field(
        default=False, json_schema_extra={"toml_path": "demo.flag"}
    )
    demo_lenient_flag: LegacyEnvBoolUnlessFalse = Field(
        default=True, json_schema_extra={"toml_path": "demo.lenient_flag"}
    )
    demo_tags: CommaSeparatedStrList = Field(
        default_factory=list, json_schema_extra={"toml_path": "demo.tags"}
    )
    demo_map: dict[str, str] | None = Field(
        default=None, json_schema_extra={"toml_path": "demo.map"}
    )
    demo_color: _DemoColor = Field(
        default=_DemoColor.RED, json_schema_extra={"toml_path": "demo.color"}
    )
    # Field whose Python name differs from its env vars — documents that env
    # matching uses ONLY the aliases once validation_alias is set.
    demo_renamed: str = Field(
        default="",
        validation_alias=AliasChoices("DEMO_ALIASED", "DEMO_ALIASED_LEGACY"),
        json_schema_extra={"toml_path": "demo.aliased"},
    )


_DEMO_ENV_VARS = [
    "DEMO_HOST",
    "DEMO_PORT",
    "DEMO_FLAG",
    "DEMO_LENIENT_FLAG",
    "DEMO_TAGS",
    "DEMO_MAP",
    "DEMO_COLOR",
    "DEMO_ALIASED",
    "DEMO_ALIASED_LEGACY",
    "DEMO_RENAMED",
]


@pytest.fixture(autouse=True)
def _clean_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_toml_document_cache()
    for name in _DEMO_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(ONYX_CONFIG_FILE_ENV_VAR, ONYX_CONFIG_FILE_DISABLED)


def _use_toml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    content: str,
    name: str = "onyx.toml",
) -> Path:
    path = tmp_path / name
    path.write_text(content)
    monkeypatch.setenv(ONYX_CONFIG_FILE_ENV_VAR, str(path))
    return path


def test_defaults_with_no_file() -> None:
    settings = _DemoSettings()
    assert settings.demo_host == "localhost"
    assert settings.demo_port == 8080
    assert settings.demo_flag is False
    assert settings.demo_tags == []
    assert settings.demo_map is None
    assert settings.demo_color is _DemoColor.RED
    assert settings.demo_renamed == ""


def test_toml_overrides_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_toml(
        monkeypatch,
        tmp_path,
        '[demo]\nhost = "from-toml"\nport = 9999\nflag = true\n',
    )
    settings = _DemoSettings()
    assert settings.demo_host == "from-toml"
    assert settings.demo_port == 9999
    assert settings.demo_flag is True


def test_env_overrides_toml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _use_toml(monkeypatch, tmp_path, '[demo]\nhost = "from-toml"\nport = 9999\n')
    monkeypatch.setenv("DEMO_HOST", "from-env")
    monkeypatch.setenv("DEMO_PORT", "1234")
    settings = _DemoSettings()
    assert settings.demo_host == "from-env"
    assert settings.demo_port == 1234


def test_empty_env_falls_through_to_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_toml(monkeypatch, tmp_path, '[demo]\nhost = "from-toml"\n')
    monkeypatch.setenv("DEMO_HOST", "")
    assert _DemoSettings().demo_host == "from-toml"


def test_empty_env_falls_through_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_HOST", "")
    monkeypatch.setenv("DEMO_PORT", "")
    settings = _DemoSettings()
    assert settings.demo_host == "localhost"
    assert settings.demo_port == 8080


def test_alias_primary_and_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_ALIASED_LEGACY", "legacy")
    assert _DemoSettings().demo_renamed == "legacy"

    monkeypatch.setenv("DEMO_ALIASED", "primary")
    # Both set: the first AliasChoices entry wins.
    assert _DemoSettings().demo_renamed == "primary"


def test_alias_priority_over_field_name(monkeypatch: pytest.MonkeyPatch) -> None:
    # populate_by_name=True means the field's own name is ALSO a valid env key
    # for aliased fields — at lower priority than every AliasChoices entry.
    monkeypatch.setenv("DEMO_RENAMED", "field-name")
    assert _DemoSettings().demo_renamed == "field-name"

    monkeypatch.setenv("DEMO_ALIASED_LEGACY", "legacy")
    assert _DemoSettings().demo_renamed == "legacy"

    monkeypatch.setenv("DEMO_ALIASED", "primary")
    assert _DemoSettings().demo_renamed == "primary"


def test_aliased_field_fills_from_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_toml(monkeypatch, tmp_path, '[demo]\naliased = "from-toml"\n')
    assert _DemoSettings().demo_renamed == "from-toml"


def test_comma_list_env_and_native_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEMO_TAGS", "a, b,,c")
    assert _DemoSettings().demo_tags == ["a", "b", "c"]

    monkeypatch.delenv("DEMO_TAGS")
    _use_toml(monkeypatch, tmp_path, '[demo]\ntags = ["a", "b"]\n')
    assert _DemoSettings().demo_tags == ["a", "b"]


def test_json_map_env_and_native_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEMO_MAP", '{"k": "v"}')
    assert _DemoSettings().demo_map == {"k": "v"}

    monkeypatch.delenv("DEMO_MAP")
    _use_toml(monkeypatch, tmp_path, '[demo.map]\nk = "v"\n')
    assert _DemoSettings().demo_map == {"k": "v"}


@pytest.mark.parametrize(
    "raw,expected",
    [("true", True), ("TRUE", True), ("1", False), ("yes", False), ("maybe", False)],
)
def test_legacy_bool_semantics(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool
) -> None:
    # Legacy `env.lower() == "true"`: anything but "true" is False — including
    # "1"/"yes", which pydantic's default bool coercion would flip to True.
    monkeypatch.setenv("DEMO_FLAG", raw)
    assert _DemoSettings().demo_flag is expected


@pytest.mark.parametrize(
    "raw,expected",
    [("false", False), ("FALSE", False), ("true", True), ("anything", True)],
)
def test_legacy_bool_unless_false_semantics(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool
) -> None:
    monkeypatch.setenv("DEMO_LENIENT_FLAG", raw)
    assert _DemoSettings().demo_lenient_flag is expected


def test_enum_from_env_and_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEMO_COLOR", "blue")
    assert _DemoSettings().demo_color is _DemoColor.BLUE

    monkeypatch.delenv("DEMO_COLOR")
    _use_toml(monkeypatch, tmp_path, '[demo]\ncolor = "blue"\n')
    assert _DemoSettings().demo_color is _DemoColor.BLUE


def test_explicit_missing_config_file_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(ONYX_CONFIG_FILE_ENV_VAR, str(tmp_path / "nope.toml"))
    with pytest.raises(FileNotFoundError, match="does not exist"):
        _DemoSettings()


def test_disabled_sentinel_reads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ONYX_CONFIG_FILE_ENV_VAR, ONYX_CONFIG_FILE_DISABLED)
    assert _DemoSettings().demo_host == "localhost"


def test_malformed_toml_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _use_toml(monkeypatch, tmp_path, "[demo\nhost =")
    with pytest.raises(ValueError, match="Malformed Onyx config file"):
        _DemoSettings()


def test_unrelated_toml_keys_are_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Keys belonging to other settings classes (or typos) must not fail here;
    # typo detection is the offline template-generator --check mode.
    _use_toml(monkeypatch, tmp_path, '[other]\nkey = 1\n\n[demo]\nhost = "from-toml"\n')
    assert _DemoSettings().demo_host == "from-toml"


def test_parse_is_memoized_per_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _use_toml(monkeypatch, tmp_path, '[demo]\nhost = "first"\n')
    assert _DemoSettings().demo_host == "first"

    # Rewriting the same path is not picked up: the document is cached.
    path.write_text('[demo]\nhost = "second"\n')
    assert _DemoSettings().demo_host == "first"

    clear_toml_document_cache()
    assert _DemoSettings().demo_host == "second"

    # A different path is a different cache key and parses fresh.
    _use_toml(monkeypatch, tmp_path, '[demo]\nhost = "third"\n', name="other.toml")
    assert _DemoSettings().demo_host == "third"
