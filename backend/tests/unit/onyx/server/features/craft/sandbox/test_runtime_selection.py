"""Runtime selection fails closed for unsupported Craft sandbox launchers."""

from __future__ import annotations

import pytest

import onyx.server.features.build.sandbox.runtime as runtime_module


@pytest.mark.parametrize("value", ["docker_firecracker", "legacy"])
def test_invalid_runtime_value_fails_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setattr(runtime_module, "CRAFT_SANDBOX_RUNTIME", value)

    with pytest.raises(ValueError, match="CRAFT_SANDBOX_RUNTIME"):
        runtime_module.get_sandbox_runtime()
