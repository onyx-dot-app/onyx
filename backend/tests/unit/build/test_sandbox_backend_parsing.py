import importlib
import os
from collections.abc import Iterator

import pytest

from onyx.server.features.build import configs


@pytest.fixture(autouse=True)
def _restore_configs() -> Iterator[None]:
    # SANDBOX_BACKEND is resolved at module import, so each case reloads the
    # module under a chosen env. Reload once more afterwards with the var cleared
    # to leave clean module state for other tests.
    yield
    os.environ.pop("SANDBOX_BACKEND", None)
    importlib.reload(configs)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("kubernetes", "kubernetes"),
        ("docker", "docker"),
        ("DOCKER", "docker"),
        ("  docker  ", "docker"),
    ],
)
def test_sandbox_backend_valid(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
) -> None:
    monkeypatch.setenv("SANDBOX_BACKEND", raw)
    reloaded = importlib.reload(configs)
    assert reloaded.SANDBOX_BACKEND.value == expected


@pytest.mark.parametrize("raw", ["", "   "])
def test_sandbox_backend_blank_uses_default(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("SANDBOX_BACKEND", raw)
    reloaded = importlib.reload(configs)
    assert reloaded.SANDBOX_BACKEND == reloaded.SandboxBackend.KUBERNETES


def test_sandbox_backend_unset_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SANDBOX_BACKEND", raising=False)
    reloaded = importlib.reload(configs)
    assert reloaded.SANDBOX_BACKEND == reloaded.SandboxBackend.KUBERNETES


@pytest.mark.parametrize("raw", ["local", "not-a-backend", "k8s"])
def test_sandbox_backend_unknown_fails_fast(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("SANDBOX_BACKEND", raw)
    with pytest.raises(ValueError) as exc_info:
        importlib.reload(configs)
    # error names the bad value and the valid options
    assert raw in str(exc_info.value)
    assert "kubernetes" in str(exc_info.value)
    assert "docker" in str(exc_info.value)
