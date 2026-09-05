"""Source operations: the per-connector gateway for all remote source calls.

Validation that is written as parallel probe code duplicates the connector's API
calls and drifts as the connector evolves. The source operations layer makes
that drift structurally hard: each migrated connector has one conspicuous
gateway class (``backend/onyx/connectors/<source>/ source_operations.py``)
subclassing ``SourceOperations``, and every remote interaction with the source
is a method on it. Connector indexing code, EE perm-sync code, and capability
checks all call these methods and nothing else makes source API calls.

Every public method on a gateway must be classified via the
``@source_operation`` decorator; ``__init_subclass__`` raises at import time
otherwise. Operations return plain data (dicts/models), never live SDK objects:
lazy-loading libraries (PyGithub attribute access, office365 fluent chains) can
fire requests outside any wrapper, and returning plain data is what makes the
gateway boundary real.
"""

import functools
import inspect
from abc import ABC
from collections.abc import Callable, Collection, Mapping
from enum import Enum
from types import FunctionType, MappingProxyType
from typing import Any, ClassVar, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.interfaces import CredentialsProviderInterface

_SPEC_ATTR = "__source_operation_spec__"

_F = TypeVar("_F", bound=Callable[..., Any])


class OperationConsumes(str, Enum):
    """What an operation needs in order to run.

    Capability checks composing an operation derive their skip semantics from
    this: config-consuming operations cannot run on config-less credential-time
    report runs.
    """

    CREDENTIAL = "credential"
    CONFIG = "config"
    BOTH = "both"
    NEITHER = "neither"


class SourceOperationSpec(BaseModel):
    """Metadata stamped on one gateway method by ``@source_operation``."""

    model_config = ConfigDict(frozen=True)

    name: str
    capabilities: frozenset[CredentialCapability]
    # Named forms of the operation where a parameter changes the required
    # permission (e.g. Slack ``conversations.list`` public vs private). Coverage
    # is counted per (operation, variant); empty means the operation itself is
    # the single coverage unit. A variant-bearing operation must be invoked with
    # a ``variant="<name>"`` keyword -- the method may branch on it or ignore
    # it, but the call site must classify itself.
    variants: tuple[str, ...] = ()
    consumes: OperationConsumes
    # Exempts the operation (all variants) from the check-coverage requirement.
    # The reason string is mandatory and reviewable: e.g. side effects (e.g.
    # ``conversations.join``), graceful production degradation, or "not yet
    # tested" during incremental migration. To exempt a single variant, split it
    # into its own operation and annotate the split-off half: a variant that
    # permanently cannot be probed while its sibling can is a different
    # operation.
    untested: str | None = None


def source_operation(
    *,
    capabilities: Collection[CredentialCapability],
    consumes: OperationConsumes,
    variants: Collection[str] = (),
    untested: str | None = None,
) -> Callable[[_F], _F]:
    """Classifies one gateway method as a source operation.

    Raises at decoration (import) time for malformed metadata, so a bad
    classification can never register.
    """
    # Snapshot before validating so a caller-held collection mutated after this
    # factory returns cannot bypass the checks below.
    capability_set = frozenset(capabilities)
    if not capability_set:
        raise ValueError("A source operation must serve at least one capability.")
    variant_list = list(variants)
    if len(set(variant_list)) != len(variant_list):
        raise ValueError(f"Duplicate variants: {variant_list}.")
    if any(not variant for variant in variant_list):
        raise ValueError("Variant names must be non-empty.")
    if untested is not None and not untested.strip():
        raise ValueError("An untested exemption requires a non-empty reason string.")

    def stamp(func: _F) -> _F:
        setattr(
            func,
            _SPEC_ATTR,
            SourceOperationSpec(
                # The cast is safe for anything that ultimately registers: the
                # class-level scan rejects everything but plain functions.
                name=cast(FunctionType, func).__name__,
                capabilities=capability_set,
                variants=tuple(variant_list),
                consumes=consumes,
                untested=untested,
            ),
        )
        return func

    return stamp


def _enforce_variant_kwarg(
    func: Callable[..., Any], spec: SourceOperationSpec
) -> Callable[..., Any]:
    """Wraps a variant-bearing operation to require a declared ``variant=``."""

    @functools.wraps(func)
    def wrapped(self: "SourceOperations", *args: Any, **kwargs: Any) -> Any:
        variant = kwargs.get("variant")
        if variant not in spec.variants:
            raise TypeError(
                f"{spec.name} declares variants {spec.variants}; call it "
                f"with variant= one of those, got {variant!r}."
            )
        return func(self, *args, **kwargs)

    return wrapped


# Internal: use ``monkeypatch.setattr(module, "_SOURCE_OPERATIONS_BY_SOURCE",
# {})`` to isolate in tests.
_SOURCE_OPERATIONS_BY_SOURCE: dict[DocumentSource, type["SourceOperations"]] = {}


class SourceOperations(ABC):
    """Base class for per-connector source-operation gateways.

    Subclass contract, enforced at import time:
    - Subclass ``SourceOperations`` directly and nothing else: no mixins and
      no gateway inheritance, since inherited members would bypass the
      own-namespace scan below. Shared logic goes in private module-level
      helpers.
    - Set ``source`` to the ``DocumentSource`` the gateway serves; one gateway
      per source.
    - Declare ``sdk_modules``; an explicit empty tuple marks an SDK-less
      connector.
    - Every public method must be classified with ``@source_operation``. Helpers
      (including any staticmethod/classmethod/property) stay private; data
      models live at module level.
    - Do not override ``__init__``: every gateway is constructed through the
      framework constructor below, so the checks runner can construct any
      registered gateway uniformly. Build clients lazily inside operations or
      private helpers.

    The gateway owns client construction from the credential plus optional
    connector config; operations return plain data, never live SDK objects.
    Credentials arrive as a provider (built via
    ``build_db_credentials_provider`` for persisted credentials), which carries
    the decrypt-audit, refresh write-back, and rotation-lock guarantees.
    """

    source: ClassVar[DocumentSource]

    # The SDK module roots this gateway wraps (e.g. ``("slack_sdk",)``). The
    # import-fence test asserts these are imported only from the gateway's own
    # file within the connector's OSS and EE perm-sync directories. Every
    # gateway must declare this explicitly; an empty tuple marks a genuinely
    # SDK-less connector.
    sdk_modules: ClassVar[tuple[str, ...]]

    _operation_specs: ClassVar[Mapping[str, SourceOperationSpec]] = MappingProxyType({})

    def __init__(
        self,
        *,
        credentials_provider: CredentialsProviderInterface,
        connector_specific_config: dict[str, Any] | None = None,
    ) -> None:
        self.credentials_provider = credentials_provider
        # None on config-less credential-time runs; config-consuming operations
        # are not called then (their checks skip instead).
        self.connector_specific_config = connector_specific_config

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        if cls.__bases__ != (SourceOperations,):
            raise TypeError(
                f"{cls.__name__} must subclass SourceOperations directly and "
                "nothing else: mixins and gateway inheritance would bypass "
                "the import-time enforcement, which scans only the class's "
                "own namespace. Put shared logic in private module-level "
                "helpers."
            )

        if "__init__" in vars(cls):
            raise TypeError(
                f"{cls.__name__} must not override __init__: gateways are "
                "constructed uniformly from a credentials provider plus "
                "optional connector config. Build clients lazily inside "
                "operations or private helpers."
            )

        # Read the subclass's own namespace, like the method scan below: the
        # flat-base rule means there is nowhere else a value could come from.
        source = vars(cls).get("source")
        if not isinstance(source, DocumentSource):
            raise TypeError(f"{cls.__name__} must set ``source`` to a DocumentSource.")
        registered = _SOURCE_OPERATIONS_BY_SOURCE.get(source)
        if registered is not None:
            raise TypeError(
                f"{cls.__name__} cannot register {source.value}: already "
                f"registered by {registered.__name__}. One gateway per source."
            )
        if "sdk_modules" not in vars(cls):
            raise TypeError(
                f"{cls.__name__} must declare ``sdk_modules`` so the import "
                "fence knows what to guard; declare an explicit empty tuple "
                "for a genuinely SDK-less connector."
            )
        # Shape matters: a plain string is a Collection of single characters to
        # the fence, which would then match nothing and silently pass.
        sdk_modules = vars(cls)["sdk_modules"]
        if not isinstance(sdk_modules, tuple) or any(
            not isinstance(module, str) or not module for module in sdk_modules
        ):
            raise TypeError(
                f"{cls.__name__}.sdk_modules must be a tuple of non-empty "
                "module roots; use () for a genuinely SDK-less connector."
            )

        specs: dict[str, SourceOperationSpec] = {}
        unstamped: list[str] = []
        for name, member in vars(cls).items():
            if name.startswith("_"):
                continue
            if isinstance(member, type):
                raise TypeError(
                    f"{cls.__name__}.{name}: public nested class is not "
                    "allowed on a gateway; define data models at module level."
                )
            if isinstance(member, (staticmethod, classmethod, property)):
                raise TypeError(
                    f"{cls.__name__}.{name}: public staticmethod/classmethod/"
                    "property is not allowed on a gateway; make it private or "
                    "expose it as a stamped instance method."
                )
            # Other descriptors (``cached_property``, custom ``__get__``) are
            # not callable, so they would otherwise pass as data attributes --
            # yet they execute on attribute access, the exact lazy-call hazard
            # the gateway exists to contain. Plain functions also carry
            # ``__get__`` (method binding), hence the exclusion.
            if not inspect.isfunction(member) and hasattr(member, "__get__"):
                raise TypeError(
                    f"{cls.__name__}.{name}: public descriptor is not allowed "
                    "on a gateway; make it private or expose it as a stamped "
                    "instance method."
                )
            if not callable(member):
                continue
            spec = getattr(member, _SPEC_ATTR, None)  # ods: ignore[getattr]
            if spec is None:
                unstamped.append(name)
            elif spec.name != name:
                raise TypeError(
                    f"{cls.__name__}.{name} is an aliased assignment of the "
                    f"operation stamped as {spec.name!r}; define it as a "
                    "plain method under its own name."
                )
            else:
                specs[name] = spec
        if unstamped:
            raise TypeError(
                f"{cls.__name__} has unclassified public methods: "
                f"{unstamped}. Stamp them with @source_operation or make "
                "them private."
            )

        # Variant-bearing operations must self-classify at every call site;
        # wrapping here makes production calls carry the same ``variant=``
        # attribution the coverage harness counts, so coverage claims stay
        # honest.
        for name, spec in specs.items():
            if spec.variants:
                setattr(cls, name, _enforce_variant_kwarg(vars(cls)[name], spec))

        cls._operation_specs = MappingProxyType(specs)
        _SOURCE_OPERATIONS_BY_SOURCE[source] = cls

    @classmethod
    def operation_specs(cls) -> Mapping[str, SourceOperationSpec]:
        """Returns the specs of the operations defined on this gateway."""
        return cls._operation_specs


def get_source_operations_class(
    source: DocumentSource,
) -> type[SourceOperations] | None:
    """Returns the registered gateway class for a source, if one exists."""
    return _SOURCE_OPERATIONS_BY_SOURCE.get(source)


def registered_source_operations() -> Mapping[DocumentSource, type[SourceOperations]]:
    """Returns all registered gateways, for auto-discovering harnesses."""
    return MappingProxyType(_SOURCE_OPERATIONS_BY_SOURCE)
