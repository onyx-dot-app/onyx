"""The published chart's appVersion (helm-chart-releases.yml): the newest
stable Onyx tag. A default install of that chart (global.version "latest")
takes the Firecracker images of that release, with no global.version pin."""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.external_dependency_unit.craft_helm.rendering import (
    CHART_DIR,
    helm_template_command,
    skip_or_fail,
)

_SCRIPT = CHART_DIR.parents[3] / ".github" / "scripts" / "chart-app-version.sh"
_REGISTRATION = [
    "--set",
    "auth.sandboxNodeRegistration.enabled=true",
    "--set-string",
    "auth.sandboxNodeRegistration.values.sandbox_node_registration_secret="
    "reg-test-0123456789abcdef0123456789",
]


def _app_version(tmp_path: Path, tags: list[str]) -> str:
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--allow-empty",
        "-qm",
        "fixture",
    )
    for tag in tags:
        git("tag", tag)
    result = subprocess.run(
        ["bash", str(_SCRIPT)], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _render_published(
    tmp_path: Path, app_version: str, args: list[str]
) -> subprocess.CompletedProcess[str]:
    """Package the chart like the publish workflow, then render the tarball."""
    helm = shutil.which("helm")
    if helm is None:
        skip_or_fail("helm binary not available")
    out = tmp_path / "pkg"
    package = subprocess.run(
        [
            helm,
            "package",
            str(CHART_DIR),
            "--app-version",
            app_version,
            "--destination",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    if package.returncode != 0:
        if "missing in charts/" in package.stderr:
            skip_or_fail(f"chart dependencies not built: {package.stderr.strip()}")
        pytest.fail(f"helm package failed: {package.stderr.strip()}")
    command = helm_template_command(args)
    command[command.index(str(CHART_DIR))] = str(next(out.glob("onyx-*.tgz")))
    return subprocess.run(command, capture_output=True, text=True)


def _docs(result: subprocess.CompletedProcess[str]) -> list[dict[str, Any]]:
    assert result.returncode == 0, result.stderr
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def _find(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any] | None:
    return next(
        (d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name),
        None,
    )


def _configmap(docs: list[dict[str, Any]]) -> dict[str, str]:
    cm = _find(docs, "ConfigMap", "env-configmap")
    assert cm is not None
    return cm["data"]


def test_app_version_is_the_newest_stable_tag(tmp_path: Path) -> None:
    tags = [
        "v5.9.0",
        "v6.0.0",
        "v5.10.3",
        "v6.1.0-beta.1",
        "v6.0.1-cloud.2",
        "nightly-latest-20261126",
        "helm/onyx-0.10.0",
        "v06.2.0",
    ]
    assert _app_version(tmp_path, tags) == "v6.0.0"


def test_app_version_is_latest_without_a_stable_tag(tmp_path: Path) -> None:
    assert _app_version(tmp_path, ["v6.0.0-beta.1"]) == "latest"


def test_published_v6_chart_takes_the_release_images(tmp_path: Path) -> None:
    docs = _docs(_render_published(tmp_path, "v6.0.0", _REGISTRATION))
    agent = _find(docs, "DaemonSet", "onyx-craft-fc-host-agent")
    assert agent is not None
    spec = agent["spec"]["template"]["spec"]
    assert spec["containers"][0]["image"] == "onyxdotapp/craft-fc-host-agent:v6.0.0"
    assert spec["initContainers"][0]["image"] == (
        "onyxdotapp/craft-fc-artifacts:rootfs-v6.0.0"
    )
    data = _configmap(docs)
    assert data["SANDBOX_FC_TEMPLATE"] == "v6.0.0"
    assert data["SANDBOX_RUNTIME"] == "auto"


@pytest.mark.parametrize("version", ["latest", "latest-dev"])
def test_published_pre_v6_chart_keeps_pod_sandboxes(
    tmp_path: Path, version: str
) -> None:
    """The floating images of a v5 chart do not know "auto", and v5 has no
    Firecracker images: "auto" acts as "pod" and the tags stay unpinned."""
    docs = _docs(
        _render_published(
            tmp_path,
            "v5.2.0",
            [*_REGISTRATION, "--set-string", f"global.version={version}"],
        )
    )
    assert _find(docs, "DaemonSet", "onyx-craft-fc-host-agent") is None
    assert _configmap(docs)["SANDBOX_RUNTIME"] == "pod"

    firecracker = _render_published(
        tmp_path / "fc",
        "v5.2.0",
        [*_REGISTRATION, "--set", "craft.sandboxRuntime=firecracker"],
    )
    assert firecracker.returncode != 0
    assert "pinned" in firecracker.stderr


def test_explicit_v6_backend_tags_win_over_a_pre_v6_app_version(
    tmp_path: Path,
) -> None:
    """The appVersion describes only the images without a tag of their own."""
    v6_tags = [
        *_REGISTRATION,
        "--set-string",
        "api.image.tag=v6.0.0",
        "--set-string",
        "celery_shared.image.tag=v6.0.0",
    ]
    docs = _docs(_render_published(tmp_path, "v5.2.0", v6_tags))
    assert _configmap(docs)["SANDBOX_RUNTIME"] == "auto"

    one_tag = [*_REGISTRATION, "--set-string", "api.image.tag=v6.0.0"]
    docs = _docs(_render_published(tmp_path / "one", "v5.2.0", one_tag))
    assert _configmap(docs)["SANDBOX_RUNTIME"] == "pod"


@pytest.mark.parametrize(
    ("app_version", "runtime"), [("v5.2.0", "pod"), ("v6.0.0", "auto")]
)
def test_an_unset_global_version_acts_as_latest(
    tmp_path: Path, app_version: str, runtime: str
) -> None:
    docs = _docs(
        _render_published(
            tmp_path, app_version, [*_REGISTRATION, "--set", "global.version=null"]
        )
    )
    assert _configmap(docs)["SANDBOX_RUNTIME"] == runtime
    agent = _find(docs, "DaemonSet", "onyx-craft-fc-host-agent")
    assert (agent is not None) == (runtime == "auto")


def test_pinned_global_version_wins_over_app_version(tmp_path: Path) -> None:
    docs = _docs(
        _render_published(
            tmp_path,
            "v6.0.0",
            [*_REGISTRATION, "--set-string", "global.version=v6.1.0"],
        )
    )
    agent = _find(docs, "DaemonSet", "onyx-craft-fc-host-agent")
    assert agent is not None
    assert agent["spec"]["template"]["spec"]["containers"][0]["image"].endswith(
        ":v6.1.0"
    )


@pytest.mark.parametrize("version", ["edge", "beta"])
def test_app_version_says_nothing_about_edge_or_beta(
    tmp_path: Path, version: str
) -> None:
    """The appVersion is the release behind "latest" only. "edge" and "beta"
    keep "auto", and they take the Firecracker tags only from explicit values."""
    floating = [*_REGISTRATION, "--set-string", f"global.version={version}"]
    docs = _docs(_render_published(tmp_path / "v5", "v5.2.0", floating))
    assert _configmap(docs)["SANDBOX_RUNTIME"] == "auto"
    assert _find(docs, "DaemonSet", "onyx-craft-fc-host-agent") is None

    explicit = [
        *floating,
        "--set-string",
        "craft.hostAgent.image.tag=v6.0.0",
        "--set-string",
        "craft.hostAgent.rootfs.version=v6.0.0",
    ]
    docs = _docs(_render_published(tmp_path / "v5-tags", "v5.2.0", explicit))
    assert _find(docs, "DaemonSet", "onyx-craft-fc-host-agent") is not None

    docs = _docs(_render_published(tmp_path / "v6", "v6.0.0", floating))
    assert _find(docs, "DaemonSet", "onyx-craft-fc-host-agent") is None
