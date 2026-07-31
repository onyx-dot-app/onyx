"""Source operations: the per-connector gateway for all remote source calls.

Validation that is written as parallel probe code duplicates the connector's
API calls and drifts as the connector evolves. The source operations layer
makes that drift structurally hard: each migrated connector has one
conspicuous gateway class (``backend/onyx/connectors/<source>/
source_operations.py``) subclassing ``SourceOperations``, and every remote
interaction with the source is a method on it. Connector indexing code, EE
perm-sync code, and capability checks all call these methods and nothing else
makes source API calls.

Every public method on a gateway must be classified via the
``@source_operation`` decorator; ``__init_subclass__`` raises at import time
otherwise, so adding an unclassified source call to a gateway is impossible
rather than just discouraged. Operations return plain data (dicts/models),
never live SDK objects: lazy-loading libraries (PyGithub attribute access,
office365 fluent chains) can fire requests outside any wrapper, and returning
plain data is what makes the gateway boundary real.
"""

from abc import ABC
from collections.abc import Callable, Collection, Mapping
from enum import Enum
from types import FunctionType, MappingProxyType
from typing import Any, ClassVar, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import CredentialCapability

_SPEC_ATTR = "__source_operation_spec__"

_F = TypeVar("_F", bound=Callable[..., Any])


class OperationConsumes(str, Enum):
    """What an operation needs in order to run.

    Capability checks composing an operation derive their skip semantics from
    this: config-consuming operations cannot run on config-less
    credential-time report runs.
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
    # permission (e.g. Slack ``conversations.list`` public vs private).
    # Coverage is counted per (operation, variant); empty means the operation
    # itself is the single coverage unit.
    variants: tuple[str, ...] = ()
    consumes: OperationConsumes
    # Exempts the operation (all variants) from the check-coverage
    # requirement. The reason string is mandatory and reviewable: side effects
    # (e.g. ``conversations.join``), graceful production degradation, or "not
    # yet tested" during incremental migration.
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
    if not capabilities:
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
                # Only plain functions are stampable (the base class rejects
                # staticmethod/classmethod/property), so the cast is safe.
                name=cast(FunctionType, func).__name__,
                capabilities=frozenset(capabilities),
                variants=tuple(variant_list),
                consumes=consumes,
                untested=untested,
            ),
        )
        return func

    return stamp


# Internal: use ``monkeypatch.setattr(module, "_SOURCE_OPERATIONS_BY_SOURCE",
# {})`` to isolate in tests.
_SOURCE_OPERATIONS_BY_SOURCE: dict[DocumentSource, type["SourceOperations"]] = {}


class SourceOperations(ABC):
    """Base class for per-connector source-operation gateways.

    Subclass contract, enforced at import time:
    - Set ``source`` to the ``DocumentSource`` the gateway serves; one gateway
      per source.
    - Every public method must be classified with ``@source_operation``.
      Helpers (including any staticmethod/classmethod/property) stay private.

    The gateway owns client construction from the credential plus optional
    connector config; operations return plain data, never live SDK objects.
    """

    source: ClassVar[DocumentSource]

    _operation_specs: ClassVar[Mapping[str, SourceOperationSpec]]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        source = getattr(cls, "source", None)
        if not isinstance(source, DocumentSource):
            raise TypeError(f"{cls.__name__} must set ``source`` to a DocumentSource.")
        registered = _SOURCE_OPERATIONS_BY_SOURCE.get(source)
        if registered is not None:
            raise TypeError(
                f"{cls.__name__} cannot register {source.value}: already "
                f"registered by {registered.__name__}. One gateway per source."
            )

        specs: dict[str, SourceOperationSpec] = {}
        unstamped: list[str] = []
        for name, member in vars(cls).items():
            if name.startswith("_"):
                continue
            if isinstance(member, (staticmethod, classmethod, property)):
                raise TypeError(
                    f"{cls.__name__}.{name}: public staticmethod/classmethod/"
                    "property is not allowed on a gateway; make it private or "
                    "expose it as a stamped instance method."
                )
            if not callable(member):
                continue
            spec = getattr(member, _SPEC_ATTR, None)
            if spec is None:
                unstamped.append(name)
            else:
                specs[name] = spec
        if unstamped:
            raise TypeError(
                f"{cls.__name__} has unclassified public methods: "
                f"{unstamped}. Stamp them with @source_operation or make "
                "them private."
            )

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
