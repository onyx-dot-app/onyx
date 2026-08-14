"""Guards the shared_configs.configs facade against drifting from its schema.

The facade re-exports every SharedSettings field under its historical constant
name. That duplication is deliberate — it keeps the hundreds of
``from shared_configs.configs import X`` call sites and their types intact —
but nothing in Python makes the two lists stay in step, so these tests do.
"""

import ast
import importlib
from pathlib import Path

import pytest

from shared_configs import configs
from shared_configs.settings import SharedSettings
from shared_configs.settings_base import (
    ONYX_CONFIG_FILE_DISABLED,
    ONYX_CONFIG_FILE_ENV_VAR,
    clear_toml_document_cache,
    env_names_of,
)

FACADE_PATH = Path(configs.__file__)


@pytest.fixture(autouse=True)
def _no_config_file(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_toml_document_cache()
    monkeypatch.setenv(ONYX_CONFIG_FILE_ENV_VAR, ONYX_CONFIG_FILE_DISABLED)


def _facade_settings_exports() -> dict[str, str]:
    """{CONSTANT_NAME: settings_field} for each `X = _settings.y` assignment."""
    tree = ast.parse(FACADE_PATH.read_text(encoding="utf-8"))
    exports: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id == "_settings"
        ):
            exports[target.id] = value.attr
    return exports


def test_every_settings_field_is_re_exported() -> None:
    """A new SharedSettings field must gain a facade constant.

    Without this, a field can be added to the schema, documented in the config
    template, and still be dead: no call site can reach it.
    """
    exported_fields = set(_facade_settings_exports().values())
    missing = sorted(set(SharedSettings.model_fields) - exported_fields)
    assert not missing, (
        f"SharedSettings fields with no constant in {FACADE_PATH.name}: {missing}. "
        f"Add `NAME = _settings.{missing[0]}` there."
    )


def test_no_facade_constant_references_a_dropped_field() -> None:
    unknown = sorted(
        f
        for f in _facade_settings_exports().values()
        if f not in SharedSettings.model_fields
    )
    assert not unknown, f"facade reads fields SharedSettings no longer has: {unknown}"


def test_exported_constants_match_the_settings_values() -> None:
    """Catches a copy-paste that wires a constant to the wrong field."""
    settings = SharedSettings()
    for constant, field in _facade_settings_exports().items():
        assert getattr(configs, constant) == getattr(settings, field), (
            f"{constant} does not match _settings.{field}"
        )


def test_env_var_names_stay_upper_snake() -> None:
    """The env surface is derived from field names, so they must be legal."""
    for name, field in SharedSettings.model_fields.items():
        for env_name in env_names_of(name, field):
            assert env_name.isupper() and env_name.replace("_", "").isalnum(), (
                f"{name} exposes an unusable env var name: {env_name!r}"
            )


def test_reload_seam_rereads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`monkeypatch.setenv` + `importlib.reload` must still work.

    Many existing tests configure the backend this way; building the settings
    object at facade module scope is what preserves it.
    """
    monkeypatch.setenv("MODEL_SERVER_PORT", "4321")
    reloaded = importlib.reload(configs)
    try:
        assert reloaded.MODEL_SERVER_PORT == 4321
        # Unset fields still derive from it.
        assert reloaded.INDEXING_MODEL_SERVER_PORT == 4321
    finally:
        monkeypatch.delenv("MODEL_SERVER_PORT")
        importlib.reload(configs)


def test_env_still_beats_toml_after_reload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "onyx.toml"
    config_file.write_text("[model_server]\nport = 5555\n")
    monkeypatch.setenv(ONYX_CONFIG_FILE_ENV_VAR, str(config_file))
    clear_toml_document_cache()
    try:
        assert importlib.reload(configs).MODEL_SERVER_PORT == 5555
        monkeypatch.setenv("MODEL_SERVER_PORT", "6666")
        assert importlib.reload(configs).MODEL_SERVER_PORT == 6666
    finally:
        monkeypatch.delenv("MODEL_SERVER_PORT", raising=False)
        monkeypatch.setenv(ONYX_CONFIG_FILE_ENV_VAR, ONYX_CONFIG_FILE_DISABLED)
        clear_toml_document_cache()
        importlib.reload(configs)
