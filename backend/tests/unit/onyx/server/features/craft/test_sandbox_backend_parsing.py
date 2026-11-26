import runpy

import pytest

from onyx.server.features.build import configs


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
    monkeypatch.delenv("SANDBOX_RUNTIME", raising=False)
    settings = runpy.run_path(configs.__file__)
    assert settings["SANDBOX_BACKEND"].value == expected


@pytest.mark.parametrize("raw", ["", "   "])
def test_sandbox_backend_blank_uses_default(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("SANDBOX_BACKEND", raw)
    settings = runpy.run_path(configs.__file__)
    assert settings["SANDBOX_BACKEND"] is settings["SandboxBackend"].KUBERNETES


def test_sandbox_backend_unset_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SANDBOX_BACKEND", raising=False)
    settings = runpy.run_path(configs.__file__)
    assert settings["SANDBOX_BACKEND"] is settings["SandboxBackend"].KUBERNETES


@pytest.mark.parametrize("raw", ["local", "not-a-backend", "k8s"])
def test_sandbox_backend_unknown_fails_fast(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("SANDBOX_BACKEND", raw)
    with pytest.raises(ValueError) as exc_info:
        runpy.run_path(configs.__file__)
    # error names the bad value and the valid options
    assert raw in str(exc_info.value)
    assert "kubernetes" in str(exc_info.value)
    assert "docker" in str(exc_info.value)


@pytest.mark.parametrize(
    "raw, firecracker",
    [("pod", False), ("off", False), ("auto", True), ("FIRECRACKER", True)],
)
def test_sandbox_runtime_values(
    monkeypatch: pytest.MonkeyPatch, raw: str, firecracker: bool
) -> None:
    monkeypatch.delenv("SANDBOX_BACKEND", raising=False)
    monkeypatch.setenv("SANDBOX_RUNTIME", raw)
    settings = runpy.run_path(configs.__file__)
    assert settings["SANDBOX_RUNTIME"].value == raw.lower()
    assert settings["SANDBOX_RUNTIME"].uses_firecracker is firecracker


def test_firecracker_runtime_needs_the_kubernetes_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SANDBOX_BACKEND", "docker")
    monkeypatch.setenv("SANDBOX_RUNTIME", "firecracker")
    with pytest.raises(ValueError, match="SANDBOX_RUNTIME=firecracker requires"):
        runpy.run_path(configs.__file__)


@pytest.mark.parametrize(
    "backend, runtime, harness, firecracker, containers",
    [
        # Compose: auto never uses Firecracker.
        ("docker", "auto", "true", False, True),
        ("docker", "auto", "false", False, False),
        ("kubernetes", "auto", "true", True, True),
        ("kubernetes", "pod", "true", False, True),
        ("kubernetes", "firecracker", "true", True, False),
        ("kubernetes", "off", "true", False, False),
    ],
)
def test_harness_backends_per_runtime(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
    runtime: str,
    harness: str,
    firecracker: bool,
    containers: bool,
) -> None:
    monkeypatch.setenv("SANDBOX_BACKEND", backend)
    monkeypatch.setenv("SANDBOX_RUNTIME", runtime)
    monkeypatch.setenv("SANDBOX_CONTAINER_HARNESS", harness)
    settings = runpy.run_path(configs.__file__)
    assert settings["SANDBOX_FIRECRACKER_ENABLED"] is firecracker
    assert settings["CONTAINER_HARNESS_ENABLED"] is containers


def test_sandbox_image_fallback_is_not_derived_from_onyx_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SANDBOX_CONTAINER_IMAGE", raising=False)
    monkeypatch.setenv("ONYX_VERSION", "v4.1.2")

    settings = runpy.run_path(configs.__file__)

    assert settings["SANDBOX_CONTAINER_IMAGE"] == "onyxdotapp/sandbox:latest"


def test_sandbox_image_override_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONYX_VERSION", "v4.1.2")
    monkeypatch.setenv("SANDBOX_CONTAINER_IMAGE", "onyxdotapp/sandbox:ctx-123")

    settings = runpy.run_path(configs.__file__)

    assert settings["SANDBOX_CONTAINER_IMAGE"] == "onyxdotapp/sandbox:ctx-123"


def test_blank_sandbox_image_override_does_not_emit_blank_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONYX_VERSION", "v4.1.2")
    monkeypatch.setenv("SANDBOX_CONTAINER_IMAGE", "  ")

    settings = runpy.run_path(configs.__file__)

    assert settings["SANDBOX_CONTAINER_IMAGE"] == "onyxdotapp/sandbox:latest"


def test_sandbox_timing_defaults_match_existing_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("SANDBOX_IDLE_CLEANUP_INTERVAL_SECONDS", raising=False)

    settings = runpy.run_path(configs.__file__)

    assert settings["SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS"] == 180
    assert settings["SANDBOX_IDLE_CLEANUP_INTERVAL_SECONDS"] == 60


def test_sandbox_timing_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("SANDBOX_IDLE_CLEANUP_INTERVAL_SECONDS", "10")

    settings = runpy.run_path(configs.__file__)

    assert settings["SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS"] == 20
    assert settings["SANDBOX_IDLE_CLEANUP_INTERVAL_SECONDS"] == 10
