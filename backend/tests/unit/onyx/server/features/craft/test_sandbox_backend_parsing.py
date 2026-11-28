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
