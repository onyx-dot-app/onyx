"""Base infrastructure for Onyx's TOML-backed configuration service.

Configuration precedence, highest to lowest:

1. Environment variables — the legacy surface and per-service overrides.
2. The optional ``onyx.toml`` config file.
3. Hardcoded field defaults.

With no TOML file present, behavior matches the historical env-var-only
configuration.

The file is located via the ``ONYX_CONFIG_FILE`` env var (the literal value
``disabled`` opts out; a set-but-missing path fails loudly), falling back to
``/etc/onyx/onyx.toml``. The parsed document is memoized per resolved path for
the lifetime of the process: config facade modules build their settings class
fresh on every (re)import — which keeps the ``monkeypatch.setenv`` plus
``importlib.reload`` test pattern working — while the file is read and parsed
at most once per path.

Declare fields with :func:`onyx_field`, never with a bare ``Field``. The base
class rejects any field that skips it, so a TOML path cannot go missing or
collide by accident.

This module must stay importable by ``model_server``: stdlib and pydantic
only, never ``onyx.*``.
"""

import os
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, cast

from pydantic import AliasChoices, BeforeValidator, Field
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

ONYX_CONFIG_FILE_ENV_VAR = "ONYX_CONFIG_FILE"
# Sentinel for ONYX_CONFIG_FILE: skip file loading entirely. Tests and dev
# machines use it to guarantee no stray config file is picked up. An explicit
# nonexistent path raises, so this is the only "no file, period" knob.
ONYX_CONFIG_FILE_DISABLED = "disabled"
DEFAULT_CONFIG_FILE_PATH = Path("/etc/onyx/onyx.toml")

# json_schema_extra keys written by onyx_field.
TOML_PATH_KEY = "toml_path"
SECRET_KEY = "secret"
BLANK_IS_FALSY_KEY = "blank_is_falsy"

_MISSING = object()

_toml_document_cache: dict[Path, dict[str, Any]] = {}


# --- config file loading ------------------------------------------------------


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

    The cache lives in this module, which config facades never reload, so a
    process parses the file at most once per path while facades stay free to
    rebuild their settings on every reload (re-reading env each time). A
    changed ``ONYX_CONFIG_FILE`` is a new cache key and parses fresh. Edits to
    an already-loaded file are not picked up: restart the process, or call
    ``clear_toml_document_cache`` in tests.
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


# --- field declaration --------------------------------------------------------


def onyx_field(
    *,
    toml: str,
    description: str,
    default: Any = ...,
    default_factory: Callable[..., Any] | None = None,
    env: tuple[str, ...] = (),
    secret: bool = False,
    blank_is_falsy: bool = False,
) -> Any:
    """Declare an Onyx settings field.

    Args:
        toml: Dotted path into the TOML document, e.g. ``model_server.port``.
            Required — see :class:`OnyxBaseSettings` for why.
        description: Operator-facing help text. Feeds the config template.
        default: Static default. Omit when passing ``default_factory``.
        default_factory: Zero-arg or data-aware factory for defaults that
            derive from an earlier field, e.g.
            ``lambda data: data["model_server_port"]``.
        env: Extra env var names to accept, highest priority first. The field
            name uppercased is always accepted; list only legacy aliases here.
        secret: Marks a credential so the template generator redacts it.
        blank_is_falsy: Keep a blank env var (``FOO=``) as an empty string
            instead of treating it as unset. Needed only where the legacy code
            gave a blank value a meaning that differs from the field default —
            see :class:`_BlankAwareEnvSource`.

    Returns:
        A configured pydantic ``FieldInfo``. Typed ``Any`` so assigning it to a
        narrowly-typed field annotation type-checks, matching ``Field`` itself.
    """
    extra: dict[str, Any] = {
        TOML_PATH_KEY: toml,
        SECRET_KEY: secret,
        BLANK_IS_FALSY_KEY: blank_is_falsy,
    }
    validation_alias = AliasChoices(*env) if env else None
    if default_factory is not None:
        return Field(
            default_factory=default_factory,
            validation_alias=validation_alias,
            json_schema_extra=extra,
            description=description,
        )
    return Field(
        default=default,
        validation_alias=validation_alias,
        json_schema_extra=extra,
        description=description,
    )


def _field_extra(field: FieldInfo) -> dict[str, Any]:
    extra = field.json_schema_extra
    return cast(dict[str, Any], extra) if isinstance(extra, dict) else {}


def toml_path_of(field: FieldInfo) -> str | None:
    value = _field_extra(field).get(TOML_PATH_KEY)
    return value if isinstance(value, str) else None


def is_secret(field: FieldInfo) -> bool:
    return _field_extra(field).get(SECRET_KEY) is True


def _blank_is_falsy(field: FieldInfo) -> bool:
    return _field_extra(field).get(BLANK_IS_FALSY_KEY) is True


def primary_key_of(field_name: str, field: FieldInfo) -> str:
    """The key a settings source must use to populate this field.

    ``populate_by_name`` is off (see :class:`OnyxBaseSettings`), so an aliased
    field is reachable only through its aliases — non-env sources have to key
    by the primary alias. An unaliased field keys by its plain Python name.
    """
    alias = field.validation_alias
    if isinstance(alias, AliasChoices):
        return str(alias.choices[0])
    if isinstance(alias, str):
        return alias
    return field_name


def env_names_of(field_name: str, field: FieldInfo) -> list[str]:
    """Every env var name that can populate this field, highest priority first.

    Exactly the declared surface: the aliases when ``env=`` was given, else the
    field name uppercased. Nothing implicit — a field never gains an extra env
    var just because of how it is spelled in Python. Kept in sync with the env
    source so tooling (the drift inventory, the template generator) can
    enumerate the real env surface without importing settings.
    """
    alias = field.validation_alias
    if isinstance(alias, AliasChoices):
        return [str(choice).upper() for choice in alias.choices]
    if isinstance(alias, str):
        return [alias.upper()]
    return [field_name.upper()]


# --- settings sources ---------------------------------------------------------


def _get_nested(document: dict[str, Any], dotted_path: str) -> Any:
    node: Any = document
    for part in dotted_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


class _BlankAwareEnvSource(PydanticBaseSettingsSource):
    """Env source that drops blank values, per field.

    Almost every legacy read used ``os.environ.get("FOO") or default``, so a
    blank ``FOO=`` meant "unset" — pydantic-settings spells this
    ``env_ignore_empty=True``, but only globally. A handful of legacy reads
    instead gave blank a meaning that differs from the default:

        SKIP_WARM_UP="" -> False, while the default is True

    Under a global ignore-empty those flags would silently flip when a
    deployment renders an unset value as an empty string (Helm does this), so
    blank handling is per-field: ignored by default, kept when the field is
    declared ``blank_is_falsy=True``.
    """

    def __init__(
        self, settings_cls: type[BaseSettings], inner: PydanticBaseSettingsSource
    ) -> None:
        super().__init__(settings_cls)
        self._inner = inner
        # The env source keys by field name for plain fields and by alias for
        # aliased ones, so match on both, case-insensitively.
        self._keep_blank: set[str] = set()
        for name, field in settings_cls.model_fields.items():
            if not _blank_is_falsy(field):
                continue
            self._keep_blank.add(name.lower())
            self._keep_blank.update(n.lower() for n in env_names_of(name, field))

    def get_field_value(
        self,
        field: FieldInfo,  # noqa: ARG002 — signature fixed by the base class
        field_name: str,
    ) -> tuple[Any, str, bool]:
        # Unused: __call__ returns the whole mapping at once.
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        return {
            name: value
            for name, value in self._inner().items()
            if value != "" or name.lower() in self._keep_blank
        }


class OnyxTomlSource(PydanticBaseSettingsSource):
    """Settings source reading the shared onyx.toml file.

    Flattens nested TOML tables into a mapping keyed by each field's primary
    validation key, pulling each value from the dotted TOML path declared via
    :func:`onyx_field`. Aliased fields are keyed by their primary alias because
    ``populate_by_name`` is off — the field name alone would not populate them.

    TOML values are already native Python types (tomllib), so no string
    decoding happens here. Document keys matching no field are ignored: this
    class cannot tell a typo from a key belonging to one of the *other*
    settings classes reading the same file, so typo detection belongs in the
    offline template checker.
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        document = load_toml_document()
        values: dict[str, Any] = {}
        for field_name, field in settings_cls.model_fields.items():
            path = toml_path_of(field)
            if path is None:
                continue
            value = _get_nested(document, path)
            if value is not _MISSING:
                values[primary_key_of(field_name, field)] = value
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


# --- base class ---------------------------------------------------------------


class OnyxBaseSettings(BaseSettings):
    """Base class for Onyx settings groups.

    Conventions, enforced by ``__pydantic_init_subclass__`` rather than left to
    review:

    - Every field is declared with :func:`onyx_field`. A field that carries no
      TOML path is a hard error, so it cannot silently become env-only or fall
      back to a bare-name path that no config template documents.
    - Two fields cannot claim the same TOML path, and no path may be a prefix
      of another (``a.b`` versus ``a.b.c``): both make the document ambiguous.
    - Field names are the lowercased legacy env var names, so the env source
      matches legacy vars with no per-field configuration. Extra legacy names
      go in ``onyx_field(env=(...))``, highest priority first — and once
      ``env=`` is given it is the *complete* list, including the field's own
      name if that should still work.

    ``populate_by_name`` is deliberately off. With it on, every field also
    answers to its Python name as an env var, so an aliased field silently
    grows an extra undocumented knob that no template mentions and no reviewer
    asked for. Keeping it off means the env surface is exactly what
    :func:`env_names_of` reports, which is what the drift inventory reads.
    """

    model_config = SettingsConfigDict(
        populate_by_name=False,
        extra="ignore",
        # Blank handling is per-field, in _BlankAwareEnvSource. Leave the
        # global switch off so it cannot double-apply.
        env_ignore_empty=False,
        case_sensitive=False,
        validate_default=True,
    )

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        seen: dict[str, str] = {}
        for field_name, field in cls.model_fields.items():
            path = toml_path_of(field)
            if path is None:
                raise TypeError(
                    f"{cls.__name__}.{field_name} must be declared with "
                    f"onyx_field(toml=...); a bare Field has no TOML path."
                )
            if path in seen:
                raise TypeError(
                    f"{cls.__name__}: fields {seen[path]!r} and {field_name!r} "
                    f"both map to TOML path {path!r}."
                )
            seen[path] = field_name
        for path, field_name in seen.items():
            parts = path.split(".")
            for depth in range(1, len(parts)):
                ancestor = ".".join(parts[:depth])
                if ancestor in seen:
                    raise TypeError(
                        f"{cls.__name__}: TOML path {path!r} ({field_name}) nests "
                        f"under {ancestor!r} ({seen[ancestor]}), which is a value."
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
        return (
            init_settings,
            _BlankAwareEnvSource(settings_cls, env_settings),
            OnyxTomlSource(settings_cls),
        )


# --- legacy coercion annotations ----------------------------------------------


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


# Bool with the dominant legacy idiom's semantics, `env.lower() == "true"`.
# Notably "1"/"yes" read as False, unlike pydantic's default bool coercion,
# which would silently FLIP such deployments to True. Native TOML bools pass
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
