from onyx.db.enums import HookPoint
from onyx.hooks.points.base import HookPointSpec
from onyx.hooks.points.document_ingestion import DocumentIngestionSpec
from onyx.hooks.points.query_processing import QueryProcessingSpec

# Internal: use `monkeypatch.setattr(registry_module, "_REGISTRY", {...})` to override in tests.
_REGISTRY: dict[HookPoint, HookPointSpec] = {
    HookPoint.DOCUMENT_INGESTION: DocumentIngestionSpec(),
    HookPoint.QUERY_PROCESSING: QueryProcessingSpec(),
}


def validate_registry() -> None:
    """Assert that every HookPoint enum value has a registered spec.

    Call once at application startup (e.g. from the FastAPI lifespan hook).
    Raises RuntimeError if any hook point is missing a spec.
    """
    missing = set(HookPoint) - set(_REGISTRY)
    if missing:
        raise RuntimeError(
            f"Hook point(s) have no registered spec: {missing}. "
            "Add an entry to onyx.hooks.registry._REGISTRY."
        )


def get_hook_point_spec(hook_point: HookPoint) -> HookPointSpec:
    """Returns the spec for a given hook point.

    Raises ValueError if the hook point has no registered spec — this is a
    programmer error; every HookPoint enum value must have a corresponding spec
    in _REGISTRY.
    """
    try:
        return _REGISTRY[hook_point]
    except KeyError:
        raise ValueError(
            f"No spec registered for hook point {hook_point!r}. "
            "Add an entry to onyx.hooks.registry._REGISTRY."
        )


def get_all_specs() -> list[HookPointSpec]:
    """Returns the specs for all registered hook points."""
    return list(_REGISTRY.values())
