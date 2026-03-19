import pytest

from onyx.db.enums import HookPoint
from onyx.hooks import registry as registry_module
from onyx.hooks.registry import get_all_specs
from onyx.hooks.registry import get_hook_point_spec
from onyx.hooks.registry import validate_registry


def test_registry_covers_all_hook_points() -> None:
    """Every HookPoint enum member must have a registered spec."""
    assert {s.hook_point for s in get_all_specs()} == set(
        HookPoint
    ), f"Missing specs for: {set(HookPoint) - {s.hook_point for s in get_all_specs()}}"


def test_get_hook_point_spec_returns_correct_spec() -> None:
    for hook_point in HookPoint:
        spec = get_hook_point_spec(hook_point)
        assert spec.hook_point == hook_point


def test_get_all_specs_returns_all() -> None:
    specs = get_all_specs()
    assert len(specs) == len(HookPoint)
    assert {s.hook_point for s in specs} == set(HookPoint)


def test_get_hook_point_spec_raises_for_unregistered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_hook_point_spec raises ValueError when a hook point has no spec."""
    monkeypatch.setattr(registry_module, "_REGISTRY", {})
    with pytest.raises(ValueError, match="No spec registered for hook point"):
        get_hook_point_spec(HookPoint.QUERY_PROCESSING)


def test_validate_registry_passes() -> None:
    validate_registry()  # should not raise with the real registry


def test_validate_registry_raises_for_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry_module, "_REGISTRY", {})
    with pytest.raises(RuntimeError, match="Hook point\\(s\\) have no registered spec"):
        validate_registry()
