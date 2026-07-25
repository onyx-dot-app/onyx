"""The reload seam: config facades construct their settings at module scope,
so `monkeypatch.setenv` + `importlib.reload(facade)` re-reads env and picks up
a changed ONYX_CONFIG_FILE — while the TOML parse itself stays memoized per
path in settings_base (which facades never reload)."""

import importlib
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

from shared_configs.settings_base import (
    ONYX_CONFIG_FILE_ENV_VAR,
    clear_toml_document_cache,
)

# importlib.reload() re-resolves the module spec through sys.path finders, so
# the facade must live on sys.path (tmp_path) and be imported by name.
_FACADE_MODULE_NAME = "toml_seam_test_facade"

_FACADE_SOURCE = textwrap.dedent(
    """
    from pydantic import Field

    from shared_configs.settings_base import OnyxBaseSettings


    class _SeamSettings(OnyxBaseSettings):
        seam_value: str = Field(
            default="default", json_schema_extra={"toml_path": "seam.value"}
        )


    _settings = _SeamSettings()
    SEAM_VALUE = _settings.seam_value
    """
)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    clear_toml_document_cache()
    monkeypatch.delenv("SEAM_VALUE", raising=False)
    yield
    sys.modules.pop(_FACADE_MODULE_NAME, None)


def test_reload_tracks_env_and_config_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    toml_one = tmp_path / "one.toml"
    toml_one.write_text('[seam]\nvalue = "one"\n')
    toml_two = tmp_path / "two.toml"
    toml_two.write_text('[seam]\nvalue = "two"\n')
    facade_path = tmp_path / f"{_FACADE_MODULE_NAME}.py"
    facade_path.write_text(_FACADE_SOURCE)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    monkeypatch.setenv(ONYX_CONFIG_FILE_ENV_VAR, str(toml_one))
    module = importlib.import_module(_FACADE_MODULE_NAME)
    assert module.SEAM_VALUE == "one"

    # Pointing ONYX_CONFIG_FILE elsewhere + reload picks up the new file.
    monkeypatch.setenv(ONYX_CONFIG_FILE_ENV_VAR, str(toml_two))
    module = importlib.reload(module)
    assert module.SEAM_VALUE == "two"

    # Rewriting an already-loaded path is NOT picked up on reload: the parsed
    # document is memoized per path for the life of the process.
    toml_two.write_text('[seam]\nvalue = "three"\n')
    module = importlib.reload(module)
    assert module.SEAM_VALUE == "two"

    # Env still beats the file on reload.
    monkeypatch.setenv("SEAM_VALUE", "env-wins")
    module = importlib.reload(module)
    assert module.SEAM_VALUE == "env-wins"
