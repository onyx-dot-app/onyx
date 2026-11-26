"""docker-compose.sandbox.yml: the opt-in Compose overlay of the Docker
container harness backend."""

from typing import Any

import yaml

from tests.common.paths import find_ancestor_containing

REPO_ROOT = find_ancestor_containing("deployment")
COMPOSE_DIR = REPO_ROOT / "deployment/docker_compose"
OVERLAY = COMPOSE_DIR / "docker-compose.sandbox.yml"
WORKERS = ("api_server", "background")


def _services(path: str = "docker-compose.sandbox.yml") -> dict[str, Any]:
    return yaml.safe_load((COMPOSE_DIR / path).read_text())["services"]


def _env(service: dict[str, Any]) -> dict[str, str]:
    return dict(item.split("=", 1) for item in service["environment"])


def test_overlay_turns_on_the_docker_container_harness() -> None:
    services = _services()
    for name in WORKERS:
        env = _env(services[name])
        assert env["SANDBOX_BACKEND"] == "docker"
        assert env["SANDBOX_RUNTIME"] == "${SANDBOX_RUNTIME:-auto}"
        assert env["SANDBOX_CONTAINER_HARNESS"] == "true"
        assert env["SANDBOX_DOCKER_RUNTIME"] == "${SANDBOX_DOCKER_RUNTIME:-}"
        assert env["SANDBOX_DOCKER_NETWORK"] == "onyx_craft_sandbox"
        assert env["SANDBOX_PROXY_HOST"] == "${SANDBOX_PROXY_HOST-sandbox-proxy}"
        assert any(
            volume.endswith(":/var/run/docker.sock")
            for volume in services[name]["volumes"]
        )
        assert services[name]["depends_on"]["sandbox-proxy"]["condition"] == (
            "service_healthy"
        )
    assert services["api_server"]["networks"]["onyx_craft_sandbox"]["aliases"] == [
        "onyx-craft-api"
    ]


def test_base_compose_mounts_no_docker_socket_on_the_workers() -> None:
    """The socket on api_server and background is opt-in (the overlay)."""
    services = _services("docker-compose.yml")
    for name in WORKERS:
        assert not any(
            "docker.sock" in str(volume) for volume in services[name].get("volumes", [])
        )


def test_prepull_names_the_image_the_sandboxes_run_and_never_runs() -> None:
    services = _services()
    prepull = services["sandbox-harness-image-prepull"]
    for name in WORKERS:
        assert _env(services[name])["SANDBOX_HARNESS_IMAGE"] == prepull["image"]
    assert prepull["image"].endswith("-container}")
    assert prepull["deploy"]["replicas"] == 0
    assert prepull["entrypoint"] == ["/bin/true"]
    for key in ("volumes", "networks", "restart"):
        assert key not in prepull


def test_shared_parts_match_the_craft_overlay() -> None:
    """Both overlays can be layered: Compose merges identical parts."""
    craft = yaml.safe_load((COMPOSE_DIR / "docker-compose.craft.yml").read_text())
    sandbox = yaml.safe_load(OVERLAY.read_text())
    assert sandbox["services"]["sandbox-proxy"] == craft["services"]["sandbox-proxy"]
    assert sandbox["networks"] == craft["networks"]
    assert sandbox["volumes"] == craft["volumes"]


def test_embedded_sandbox_compose_copy_is_in_sync() -> None:
    embedded = (
        REPO_ROOT
        / "cli/internal/deploy/deployfiles/embedded/docker_compose/docker-compose.sandbox.yml"
    )
    assert embedded.read_text() == OVERLAY.read_text()
