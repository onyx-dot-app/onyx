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
    os.environ.pop("SANDBOX_CONTAINER_IMAGE", None)
    os.environ.pop("ONYX_VERSION", None)
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


def test_sandbox_image_fallback_is_not_derived_from_onyx_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SANDBOX_CONTAINER_IMAGE", raising=False)
    monkeypatch.setenv("ONYX_VERSION", "v4.1.2")

    reloaded = importlib.reload(configs)

    assert reloaded.SANDBOX_CONTAINER_IMAGE == "onyxdotapp/sandbox:latest"


def test_sandbox_image_override_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONYX_VERSION", "v4.1.2")
    monkeypatch.setenv("SANDBOX_CONTAINER_IMAGE", "onyxdotapp/sandbox:ctx-123")

    reloaded = importlib.reload(configs)

    assert reloaded.SANDBOX_CONTAINER_IMAGE == "onyxdotapp/sandbox:ctx-123"


def test_blank_sandbox_image_override_does_not_emit_blank_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONYX_VERSION", "v4.1.2")
    monkeypatch.setenv("SANDBOX_CONTAINER_IMAGE", "  ")

    reloaded = importlib.reload(configs)

    assert reloaded.SANDBOX_CONTAINER_IMAGE == "onyxdotapp/sandbox:latest"
