"""Unit tests for the TOML settings loader in shared_configs.settings_base.

Uses a synthetic settings class so the tests do not depend on any real config
module's schema.
"""

from enum import Enum
from pathlib import Path

import pytest

from shared_configs.settings_base import (
    ONYX_CONFIG_FILE_DISABLED,
    ONYX_CONFIG_FILE_ENV_VAR,
    CommaSeparatedStrList,
    LegacyEnvBool,
    LegacyEnvBoolUnlessFalse,
    OnyxBaseSettings,
    clear_toml_document_cache,
    env_names_of,
    onyx_field,
)


class _DemoColor(str, Enum):
    RED = "red"
    BLUE = "blue"


class _DemoSettings(OnyxBaseSettings):
    demo_host: str = onyx_field(default="localhost", toml="demo.host", description="d")
    demo_port: int = onyx_field(default=8080, toml="demo.port", description="d")
    demo_flag: LegacyEnvBool = onyx_field(
        default=False, toml="demo.flag", description="d"
    )
    demo_lenient_flag: LegacyEnvBoolUnlessFalse = onyx_field(
        default=True, toml="demo.lenient_flag", description="d"
    )
    demo_blank_flag: LegacyEnvBool = onyx_field(
        default=True, toml="demo.blank_flag", description="d", blank_is_falsy=True
    )
    demo_tags: CommaSeparatedStrList = onyx_field(
        default_factory=list, toml="demo.tags", description="d"
    )
    demo_map: dict[str, str] | None = onyx_field(
        default=None, toml="demo.map", description="d"
    )
    demo_color: _DemoColor = onyx_field(
        default=_DemoColor.RED, toml="demo.color", description="d"
    )
    demo_derived: int = onyx_field(
        default_factory=lambda data: data["demo_port"],
        toml="demo.derived",
        description="d",
    )
    # Aliased field: reachable ONLY via the declared env names.
    demo_renamed: str = onyx_field(
        default="",
        env=("DEMO_ALIASED", "DEMO_ALIASED_LEGACY"),
        toml="demo.aliased",
        description="d",
    )


_DEMO_ENV_VARS = [
    "DEMO_HOST",
    "DEMO_PORT",
    "DEMO_FLAG",
    "DEMO_LENIENT_FLAG",
    "DEMO_BLANK_FLAG",
    "DEMO_TAGS",
    "DEMO_MAP",
    "DEMO_COLOR",
    "DEMO_DERIVED",
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


def _use_toml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str) -> Path:
    path = tmp_path / "onyx.toml"
    path.write_text(content)
    monkeypatch.setenv(ONYX_CONFIG_FILE_ENV_VAR, str(path))
    return path


# --- precedence ---------------------------------------------------------------


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
    _use_toml(monkeypatch, tmp_path, '[demo]\nhost = "from-toml"\nport = 1234\n')
    settings = _DemoSettings()
    assert settings.demo_host == "from-toml"
    assert settings.demo_port == 1234


def test_env_beats_toml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _use_toml(monkeypatch, tmp_path, '[demo]\nhost = "from-toml"\n')
    monkeypatch.setenv("DEMO_HOST", "from-env")
    assert _DemoSettings().demo_host == "from-env"


def test_data_aware_default_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _DemoSettings().demo_derived == 8080
    monkeypatch.setenv("DEMO_PORT", "77")
    assert _DemoSettings().demo_derived == 77
    monkeypatch.setenv("DEMO_DERIVED", "99")
    assert _DemoSettings().demo_derived == 99


# --- blank handling -----------------------------------------------------------


def test_blank_env_falls_through_to_default() -> None:
    """The dominant legacy idiom: `os.environ.get("X") or default`."""
    import os

    os.environ["DEMO_HOST"] = ""
    try:
        assert _DemoSettings().demo_host == "localhost"
    finally:
        del os.environ["DEMO_HOST"]


def test_blank_env_falls_through_to_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_toml(monkeypatch, tmp_path, '[demo]\nhost = "from-toml"\n')
    monkeypatch.setenv("DEMO_HOST", "")
    assert _DemoSettings().demo_host == "from-toml"


def test_blank_is_falsy_field_keeps_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    """blank_is_falsy=True preserves legacy reads where blank meant False.

    Without it a flag defaulting to True would silently flip on when a
    deployment renders an unset value as an empty string.
    """
    assert _DemoSettings().demo_blank_flag is True
    monkeypatch.setenv("DEMO_BLANK_FLAG", "")
    assert _DemoSettings().demo_blank_flag is False


def test_blank_is_falsy_does_not_leak_to_other_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_BLANK_FLAG", "")
    monkeypatch.setenv("DEMO_HOST", "")
    settings = _DemoSettings()
    assert settings.demo_blank_flag is False
    assert settings.demo_host == "localhost"


# --- legacy coercions ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("TRUE", True), ("True", True), ("false", False), ("1", False)],
)
def test_legacy_bool_matches_lower_eq_true(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool
) -> None:
    """`FOO=1` must stay False — pydantic's native bool coercion says True."""
    monkeypatch.setenv("DEMO_FLAG", raw)
    assert _DemoSettings().demo_flag is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("false", False), ("FALSE", False), ("true", True), ("1", True), ("yes", True)],
)
def test_legacy_bool_unless_false(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool
) -> None:
    monkeypatch.setenv("DEMO_LENIENT_FLAG", raw)
    assert _DemoSettings().demo_lenient_flag is expected


def test_native_toml_bool_passes_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_toml(monkeypatch, tmp_path, "[demo]\nflag = true\nlenient_flag = false\n")
    settings = _DemoSettings()
    assert settings.demo_flag is True
    assert settings.demo_lenient_flag is False


def test_comma_list_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_TAGS", " a , b ,, c ")
    assert _DemoSettings().demo_tags == ["a", "b", "c"]


def test_comma_list_from_toml_array(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_toml(monkeypatch, tmp_path, '[demo]\ntags = ["a", "b"]\n')
    assert _DemoSettings().demo_tags == ["a", "b"]


def test_json_and_enum_coercion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEMO_MAP", '{"k": "v"}')
    monkeypatch.setenv("DEMO_COLOR", "blue")
    settings = _DemoSettings()
    assert settings.demo_map == {"k": "v"}
    assert settings.demo_color is _DemoColor.BLUE

    monkeypatch.delenv("DEMO_MAP")
    monkeypatch.delenv("DEMO_COLOR")
    _use_toml(monkeypatch, tmp_path, '[demo.map]\nk = "v"\n')
    assert _DemoSettings().demo_map == {"k": "v"}


# --- aliases ------------------------------------------------------------------


def test_alias_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_ALIASED_LEGACY", "legacy")
    assert _DemoSettings().demo_renamed == "legacy"
    monkeypatch.setenv("DEMO_ALIASED", "primary")
    assert _DemoSettings().demo_renamed == "primary"


def test_field_name_is_not_an_env_var_when_aliased(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An aliased field must NOT also answer to its Python name.

    populate_by_name would grant every aliased field a second, undocumented
    env var that no deployment template mentions and no drift gate expects.
    """
    monkeypatch.setenv("DEMO_RENAMED", "field-name")
    assert _DemoSettings().demo_renamed == ""


def test_aliased_field_fills_from_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use_toml(monkeypatch, tmp_path, '[demo]\naliased = "from-toml"\n')
    assert _DemoSettings().demo_renamed == "from-toml"


def test_env_names_of_reports_the_real_surface() -> None:
    fields = _DemoSettings.model_fields
    assert env_names_of("demo_host", fields["demo_host"]) == ["DEMO_HOST"]
    assert env_names_of("demo_renamed", fields["demo_renamed"]) == [
        "DEMO_ALIASED",
        "DEMO_ALIASED_LEGACY",
    ]


# --- config file resolution ---------------------------------------------------


def test_missing_default_path_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ONYX_CONFIG_FILE_ENV_VAR, raising=False)
    # /etc/onyx/onyx.toml is absent in test environments; absence is silent.
    assert _DemoSettings().demo_host == "localhost"


def test_explicit_missing_path_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(ONYX_CONFIG_FILE_ENV_VAR, str(tmp_path / "nope.toml"))
    with pytest.raises(FileNotFoundError):
        _DemoSettings()


def test_malformed_file_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _use_toml(monkeypatch, tmp_path, "[demo\nhost = ")
    with pytest.raises(ValueError, match="Malformed Onyx config file"):
        _DemoSettings()


def test_document_is_memoized_per_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _use_toml(monkeypatch, tmp_path, '[demo]\nhost = "first"\n')
    assert _DemoSettings().demo_host == "first"
    path.write_text('[demo]\nhost = "second"\n')
    # Same path: the parsed document is reused, so the edit is not picked up.
    assert _DemoSettings().demo_host == "first"
    clear_toml_document_cache()
    assert _DemoSettings().demo_host == "second"


# --- schema guardrails --------------------------------------------------------


def test_bare_field_is_rejected() -> None:
    from pydantic import Field

    with pytest.raises(TypeError, match="must be declared with onyx_field"):

        class _Bad(OnyxBaseSettings):
            oops: str = Field(default="x")


def test_duplicate_toml_path_is_rejected() -> None:
    with pytest.raises(TypeError, match="both map to TOML path"):

        class _Bad(OnyxBaseSettings):
            one: str = onyx_field(default="", toml="a.b", description="d")
            two: str = onyx_field(default="", toml="a.b", description="d")


def test_toml_path_nested_under_a_value_is_rejected() -> None:
    with pytest.raises(TypeError, match="nests under"):

        class _Bad(OnyxBaseSettings):
            parent: str = onyx_field(default="", toml="a.b", description="d")
            child: str = onyx_field(default="", toml="a.b.c", description="d")
