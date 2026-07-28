"""Base infrastructure for Onyx's TOML-backed configuration service.

Configuration precedence, highest to lowest:

1. Environment variables — the legacy surface and per-service overrides.
2. The optional ``onyx.toml`` config file.
3. Hardcoded field defaults.

With no TOML file present, behavior is identical to the historical
env-var-only configuration.

The file is located via the ``ONYX_CONFIG_FILE`` env var (the literal value
``disabled`` opts out entirely; a set-but-missing path fails loudly), falling
back to ``/etc/onyx/onyx.toml``. The parsed document is memoized per resolved
path for the lifetime of the process: config facade modules construct their
settings class fresh on every (re)import — which is what keeps
``monkeypatch.setenv`` + ``importlib.reload`` test patterns working — while
the file itself is read and parsed at most once per path.

This module must stay importable by ``model_server``: stdlib + pydantic only,
never ``onyx.*``.
"""

import os
import tomllib
from pathlib import Path
from typing import Annotated, Any, cast

from pydantic import BeforeValidator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

ONYX_CONFIG_FILE_ENV_VAR = "ONYX_CONFIG_FILE"
# Sentinel for ONYX_CONFIG_FILE: skip file loading entirely. Used by tests and
# dev machines to guarantee no stray config file is picked up (an explicit
# nonexistent path raises instead, so this is the only "no file, period" knob).
ONYX_CONFIG_FILE_DISABLED = "disabled"
DEFAULT_CONFIG_FILE_PATH = Path("/etc/onyx/onyx.toml")

_MISSING = object()

_toml_document_cache: dict[Path, dict[str, Any]] = {}


def resolve_config_file() -> Path | None:
    """Resolve the TOML config file path, or None when no file should load.

    An explicitly configured path that does not exist raises: a typo'd
    ``ONYX_CONFIG_FILE`` must never silently degrade to "no config".
    """
    override = os.environ.get(ONYX_CONFIG_FILE_ENV_VAR)
    if override:
        if override == ONYX_CONFIG_FILE_DISABLED:
            return None
        path = Path(override)
        if not path.is_file():
            raise FileNotFoundError(
                f"{ONYX_CONFIG_FILE_ENV_VAR}={override!r} does not exist"
            )
        return path
    if DEFAULT_CONFIG_FILE_PATH.is_file():
        return DEFAULT_CONFIG_FILE_PATH
    return None


def load_toml_document() -> dict[str, Any]:
    """Load the config file, memoized per resolved path.

    The cache lives in this module, which config facades never reload — so a
    process parses the file at most once per path, while facades stay free to
    re-construct their settings on every reload (re-reading env each time). A
    changed ``ONYX_CONFIG_FILE`` is a new cache key and parses fresh; edits to
    an already-loaded file are intentionally not picked up (restart the
    process, or call ``clear_toml_document_cache`` in tests).
    """
    path = resolve_config_file()
    if path is None:
        return {}
    cached = _toml_document_cache.get(path)
    if cached is not None:
        return cached
    with path.open("rb") as file:
        try:
            document = tomllib.load(file)
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"Malformed Onyx config file at {path}: {e}") from e
    _toml_document_cache[path] = document
    return document


def clear_toml_document_cache() -> None:
    _toml_document_cache.clear()


def _toml_path_for(field_name: str, field: FieldInfo) -> str:
    extra = field.json_schema_extra
    if not isinstance(extra, dict):
        return field_name
    toml_path = cast(dict[str, Any], extra).get("toml_path")
    return toml_path if isinstance(toml_path, str) else field_name


def _get_nested(document: dict[str, Any], dotted_path: str) -> Any:
    node: Any = document
    for part in dotted_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


class OnyxTomlFlattenedSource(PydanticBaseSettingsSource):
    """Settings source reading the shared onyx.toml file.

    Flattens nested TOML tables into a mapping keyed by each field's plain
    Python name (never by alias), pulling each value from the dotted
    ``toml_path`` declared in the field's ``json_schema_extra`` (defaulting to
    the bare field name). Keying by field name is what makes aliased fields
    work: ``populate_by_name=True`` on the model accepts field-name keys even
    when a ``validation_alias`` is present, while env-sourced values arrive
    keyed by alias and therefore win during validation.

    TOML values are already native Python types (tomllib), so no string
    decoding happens here. Document keys matching no field are ignored: this
    class cannot distinguish a typo from a key belonging to one of the *other*
    settings classes reading the same file, so typo detection lives in the
    offline template-generator ``--check`` mode instead.
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        document = load_toml_document()
        values: dict[str, Any] = {}
        for field_name, field in settings_cls.model_fields.items():
            value = _get_nested(document, _toml_path_for(field_name, field))
            if value is not _MISSING:
                values[field_name] = value
        self._values = values

    def get_field_value(
        self,
        field: FieldInfo,  # noqa: ARG002 — signature fixed by the base class
        field_name: str,
    ) -> tuple[Any, str, bool]:
        # Unused: __call__ returns the whole prebuilt mapping at once.
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        return self._values


class OnyxBaseSettings(BaseSettings):
    """Base class for Onyx settings groups.

    Field conventions:

    - Field names are the lowercased legacy env var names, so the vanilla env
      source matches legacy env vars with no per-field configuration.
    - ``json_schema_extra={"toml_path": "section.key", "secret": bool}`` maps
      a field into the nested TOML document (default: the bare field name) and
      marks secrets for the template generator.
    - Aliases: for fields with ``validation_alias``, the env source checks the
      ``AliasChoices`` entries in order, then (because of
      ``populate_by_name=True``) the plain field name at lowest priority.
      Convention: the field name equals the primary env var name, and
      ``AliasChoices`` lists that primary name first with legacy fallbacks
      after it. (``populate_by_name=True`` is also what lets the TOML source
      fill aliased fields by field name.)
    """

    model_config = SettingsConfigDict(
        populate_by_name=True,
        extra="ignore",
        # Blank env vars (FOO=) count as unset, preserving the dominant
        # historical `os.environ.get("FOO") or default` idiom.
        env_ignore_empty=True,
        case_sensitive=False,
        validate_default=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,  # noqa: ARG003 — keyword-called by pydantic-settings
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003 — keyword-called by pydantic-settings
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Earlier entries win: env var > TOML > field default. The dotenv and
        # file-secret sources are deliberately dropped — Onyx loads .env files
        # outside the process (ods / docker / test harnesses), never here.
        return (init_settings, env_settings, OnyxTomlFlattenedSource(settings_cls))


def _coerce_legacy_env_bool(value: object) -> object:
    if isinstance(value, str):
        return value.lower() == "true"
    return value


def _coerce_legacy_env_bool_unless_false(value: object) -> object:
    if isinstance(value, str):
        return value.lower() != "false"
    return value


def _split_comma_separated(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


# Bool with the dominant legacy idiom's semantics, `env.lower() == "true"`:
# notably "1"/"yes" read as False, unlike pydantic's default bool coercion
# (which would silently FLIP such deployments to True). Native TOML bools pass
# through untouched.
LegacyEnvBool = Annotated[bool, BeforeValidator(_coerce_legacy_env_bool)]

# Bool with the inverted legacy idiom's semantics, `env.lower() != "false"`:
# any string other than "false" reads as True.
LegacyEnvBoolUnlessFalse = Annotated[
    bool, BeforeValidator(_coerce_legacy_env_bool_unless_false)
]

# Comma-separated list with the common strip-and-drop-empties behavior.
# NoDecode stops the env source from attempting JSON decoding first; TOML
# arrays pass through natively. Variants (no-strip, frozenset, ...) belong in
# per-field validators on the owning settings class.
CommaSeparatedStrList = Annotated[
    list[str], NoDecode, BeforeValidator(_split_comma_separated)
]
