"""Invariants for the sandbox image-prepull DaemonSet.

The DaemonSet keeps the sandbox image resident on every node in the sandbox
pool so a user's first sandbox there doesn't pay the pull. Four properties make
it work:

  - It references the same image as the sandbox pods. A drifted tag pins layers
    nobody uses while every sandbox still cold-pulls.
  - It lands on the same nodes (nodeSelector + tolerations), or it warms the
    wrong pool.
  - It resolves pull credentials, or a private registry leaves it in
    ImagePullBackOff.
  - It stays running, because the kubelet only skips image GC for images a
    running pod references. Hence the long-lived, shell-portable command.

These are tested rather than asserted at runtime because none of them surface
as an error: the DaemonSet reports Ready (or, on the credentials case,
ImagePullBackOff on a pod nobody watches) while sandboxes go on cold-pulling at
the original latency. The only signal is provisioning being slow, which is what
the feature was meant to fix. All four are fixed at chart-render time, so a
render test catches them before deploy.

Rendering needs the ``helm`` binary and the chart's subchart tarballs, which are
gitignored, so these skip unless you have run ``helm dependency build`` on the
chart. No CI lane currently supplies both, so treat them as a local guard for
now: run them when you touch the sandbox chart templates.

Only a missing-dependency error is treated as "can't run here". Any other helm
failure is the chart being broken and fails the test — a render test that
reports a broken chart as a skip is worse than no test.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest
import yaml

# backend/tests/unit/onyx/server/features/build/sandbox/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[8]
_CHART_DIR = _REPO_ROOT / "deployment" / "helm" / "charts" / "onyx"
_PREPULLER_TEMPLATE = "templates/sandbox-image-prepuller.yaml"
_PODTEMPLATE_TEMPLATE = "templates/sandbox-podtemplate.yaml"

# The chart refuses to render without a push keypair; any valid base64 seed works.
_FAKE_PUSH_KEY = "ZmFrZWtleWZha2VrZXlmYWtla2V5ZmFrZWtleWZha2VrZXk="

# Substrings helm uses when the gitignored subchart tarballs are absent.
_MISSING_DEPS_MARKERS = (
    "found in Chart.yaml, but missing in charts/",
    "missing in charts/ directory",
    "no cached repository",
)


def _handle_render_failure(stderr: str) -> NoReturn:
    """A missing-deps error means we can't run here; anything else is a real
    chart defect and must not be laundered into a skip."""
    if any(marker in stderr for marker in _MISSING_DEPS_MARKERS):
        pytest.skip(f"chart dependencies not built: {stderr.strip()}")
    pytest.fail(f"helm template failed: {stderr.strip()}")


def _run_helm(
    template: str, extra_args: list[str] | None = None
) -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm binary not available")
    cmd = [
        helm,
        "template",
        "onyx",
        str(_CHART_DIR),
        "-n",
        "onyx",
        "-f",
        str(_CHART_DIR / "values-ci.yaml"),
        "--kube-version",
        "1.33.0",
        "--set",
        f"auth.sandboxPushSecret.values.private_key={_FAKE_PUSH_KEY}",
        *(extra_args or []),
        "--show-only",
        template,
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def _render(template: str, extra_args: list[str] | None = None) -> str:
    result = _run_helm(template, extra_args)
    if result.returncode != 0:
        _handle_render_failure(result.stderr)
    return result.stdout


def _renders_nothing(extra_args: list[str]) -> bool:
    """True when the template produced no manifest at all.

    ``--show-only`` on a template that rendered empty is a helm *error*
    ("could not find template"), not empty stdout — so a plain string check on
    stdout would pass for a genuinely broken chart too.
    """
    result = _run_helm(_PREPULLER_TEMPLATE, extra_args)
    if result.returncode == 0:
        return not result.stdout.strip().strip("-")
    if "could not find template" in result.stderr:
        return True
    _handle_render_failure(result.stderr)


def _prepuller(extra_args: list[str] | None = None) -> dict:
    """The DaemonSet. The template also emits a PriorityClass, so select by kind
    rather than assuming a single document."""
    docs = yaml.safe_load_all(_render(_PREPULLER_TEMPLATE, extra_args))
    return next(d for d in docs if d and d["kind"] == "DaemonSet")


def _prepuller_pod_spec(extra_args: list[str] | None = None) -> dict:
    return _prepuller(extra_args)["spec"]["template"]["spec"]


def test_prepuller_image_matches_the_sandbox_pod_image() -> None:
    """The whole mechanism is a no-op unless both resolve to the same ref, and
    a mismatch is invisible at runtime."""
    args = [
        "--set",
        "global.version=v9.8.7",
        "--set-string",
        "configMap.SANDBOX_CONTAINER_IMAGE=",
    ]

    prepuller_image = _prepuller_pod_spec(args)["containers"][0]["image"]
    pod_template = yaml.safe_load(_render(_PODTEMPLATE_TEMPLATE, args))
    sandbox_images = {
        c["image"]
        for c in pod_template["template"]["spec"]["containers"]
        + pod_template["template"]["spec"]["initContainers"]
    }

    assert sandbox_images == {"onyxdotapp/sandbox:v9.8.7"}
    assert prepuller_image == "onyxdotapp/sandbox:v9.8.7"


def test_prepuller_image_follows_explicit_override() -> None:
    spec = _prepuller_pod_spec(
        ["--set-string", "configMap.SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox:dev"]
    )
    assert spec["containers"][0]["image"] == "onyxdotapp/sandbox:dev"


def test_prepuller_scheduling_matches_the_sandbox_pod() -> None:
    """Warming a node the sandboxes can't be scheduled onto buys nothing."""
    prepuller = _prepuller_pod_spec()
    sandbox = yaml.safe_load(_render(_PODTEMPLATE_TEMPLATE))["template"]["spec"]

    assert prepuller["nodeSelector"] == sandbox["nodeSelector"]
    assert prepuller["tolerations"] == sandbox["tolerations"]


def test_prepuller_stays_running_to_pin_layers() -> None:
    """The kubelet only exempts images referenced by a *running* pod from image
    GC, so a one-shot pull would leave the layers evictable.

    The command must also be portable: `sleep infinity` is a GNU coreutils
    extension that dies on busybox/alpine, and a CrashLooping prepuller unpins
    the image silently.
    """
    container = _prepuller_pod_spec()["containers"][0]
    assert container["command"] == ["sh", "-c", "while :; do sleep 86400; done"]


def test_prepuller_pull_policy_matches_the_sandbox_pod() -> None:
    """Pinning the prepuller to IfNotPresent while the sandbox pods run Always
    is the tag drift this template exists to prevent, just one level down: on a
    mutable tag the sandboxes fetch the new digest and the prepuller holds the
    old one resident and GC-exempt, with nothing to restart it."""
    args = ["--set", "configMap.SANDBOX_IMAGE_PULL_POLICY=Always"]
    prepuller = _prepuller_pod_spec(args)["containers"][0]
    sandbox = yaml.safe_load(_render(_PODTEMPLATE_TEMPLATE, args))["template"]["spec"]

    assert prepuller["imagePullPolicy"] == "Always"
    assert {c["imagePullPolicy"] for c in sandbox["containers"]} == {"Always"}


def test_prepuller_pull_policy_defaults_to_if_not_present() -> None:
    """The chart default must not re-pull on every restart."""
    container = _prepuller_pod_spec()["containers"][0]
    assert container["imagePullPolicy"] == "IfNotPresent"


def test_prepuller_requests_ephemeral_storage() -> None:
    """A container with no ephemeral-storage request is invisible to the
    scheduler's disk accounting — which this repo treats as a bug (see
    test_pod_spec.test_all_containers_set_ephemeral_storage_requests). The
    prepuller writes nothing, but it must still be accounted for."""
    resources = _prepuller_pod_spec()["containers"][0]["resources"]
    assert "ephemeral-storage" in resources["requests"]
    assert "ephemeral-storage" in resources["limits"]
    assert resources["requests"] == resources["limits"]


def test_prepuller_yields_to_pending_sandbox_pods() -> None:
    """A do-nothing pod must never be the reason a sandbox fails to schedule and
    triggers a scale-up. Negative priority lets a pending sandbox preempt it;
    preemptionPolicy Never means the prepuller evicts nothing itself."""
    docs = list(yaml.safe_load_all(_render(_PREPULLER_TEMPLATE)))
    pc = next(d for d in docs if d and d["kind"] == "PriorityClass")
    ds = next(d for d in docs if d and d["kind"] == "DaemonSet")

    # Strictly below -10, cluster-autoscaler's default expendable-pods cutoff:
    # at exactly -10 the prepuller is non-expendable and a pending one can be
    # read as demand for a new node.
    assert pc["value"] < -10
    assert pc["globalDefault"] is False
    assert pc["preemptionPolicy"] == "Never"
    assert ds["spec"]["template"]["spec"]["priorityClassName"] == pc["metadata"]["name"]


def _rendered_kinds(extra_args: list[str]) -> list[str]:
    docs = yaml.safe_load_all(_render(_PREPULLER_TEMPLATE, extra_args))
    return [d["kind"] for d in docs if d]


def test_existing_priority_class_skips_creation() -> None:
    """An operator supplying their own class must not also get ours."""
    args = ["--set", "sandboxImagePrepull.priorityClassName=system-node-critical"]

    assert "PriorityClass" not in _rendered_kinds(args)
    assert _prepuller_pod_spec(args)["priorityClassName"] == "system-node-critical"


def test_priority_class_creation_can_be_declined() -> None:
    """Regression: sprig's ``merge`` treats ``false`` as empty and overwrites it
    with the default, so a merge-based defaults block silently ignored
    ``create: false``. Falsy values must survive."""
    args = ["--set", "sandboxImagePrepull.priorityClass.create=false"]

    assert "PriorityClass" not in _rendered_kinds(args)
    assert "priorityClassName" not in _prepuller_pod_spec(args)


def test_priority_class_value_zero_survives() -> None:
    """Same trap for ints: ``value: 0`` must not silently become -10."""
    pc = next(
        d
        for d in yaml.safe_load_all(
            _render(
                _PREPULLER_TEMPLATE,
                ["--set", "sandboxImagePrepull.priorityClass.value=0"],
            )
        )
        if d and d["kind"] == "PriorityClass"
    )
    assert pc["value"] == 0


def test_repull_fanout_is_tunable_for_large_pools() -> None:
    """N nodes pulling ~1GB at once is a thundering herd against the registry."""
    ds = next(
        d
        for d in yaml.safe_load_all(
            _render(
                _PREPULLER_TEMPLATE,
                ["--set-string", "sandboxImagePrepull.updateMaxUnavailable=25%"],
            )
        )
        if d and d["kind"] == "DaemonSet"
    )
    assert ds["spec"]["updateStrategy"]["rollingUpdate"]["maxUnavailable"] == "25%"


def test_prepuller_resolves_pull_credentials() -> None:
    """A private registry must not leave the prepuller in ImagePullBackOff.

    The sandbox ServiceAccount is the only route that works here, and the only
    one the sandbox PodTemplate uses. `.Values.imagePullSecrets` must NOT be
    rendered: those names refer to secrets in the release namespace, and an
    imagePullSecret is resolved in the pod's own namespace, so in the sandbox
    namespace they name nothing — a "Unable to retrieve pull secret" event and,
    on a genuinely private registry, the ImagePullBackOff this is meant to
    avoid.
    """
    args = ["--set", "imagePullSecrets[0].name=regcred"]
    prepuller = _prepuller_pod_spec(args)
    sandbox = yaml.safe_load(_render(_PODTEMPLATE_TEMPLATE, args))["template"]["spec"]

    assert "imagePullSecrets" not in prepuller
    assert "imagePullSecrets" not in sandbox
    assert prepuller["serviceAccountName"] == sandbox["serviceAccountName"]
    # The SA is for pull credentials only; this pod makes no API calls.
    assert prepuller["automountServiceAccountToken"] is False


def test_prepuller_runs_in_the_sandbox_namespace() -> None:
    """Which is why the release-namespace imagePullSecrets above can't be used."""
    assert _prepuller()["metadata"]["namespace"] == "onyx-sandboxes"


def test_prepuller_service_account_follows_the_configured_name() -> None:
    spec = _prepuller_pod_spec(
        ["--set-string", "configMap.SANDBOX_SERVICE_ACCOUNT_NAME=custom-sandbox-sa"]
    )
    assert spec["serviceAccountName"] == "custom-sandbox-sa"


def test_priority_class_name_is_namespace_scoped() -> None:
    """PriorityClass is cluster-scoped. Two same-named releases in different
    namespaces must not render the same object — the second install would fail
    Helm's ownership check, and either release's upgrade could disrupt the
    other."""

    def pc_name(namespace: str) -> str:
        docs = yaml.safe_load_all(
            _render(_PREPULLER_TEMPLATE, ["--namespace", namespace])
        )
        pc = next(d for d in docs if d and d["kind"] == "PriorityClass")
        return pc["metadata"]["name"]

    assert pc_name("onyx") != pc_name("onyx-staging")


def test_priority_class_name_stays_within_k8s_limits() -> None:
    """Long release/namespace pairs must hash down rather than emit an invalid
    name, matching the trunc+sha shape used for the RBAC names."""
    long_ns = "a" * 60
    docs = yaml.safe_load_all(_render(_PREPULLER_TEMPLATE, ["--namespace", long_ns]))
    name = next(d for d in docs if d and d["kind"] == "PriorityClass")["metadata"][
        "name"
    ]
    assert len(name) <= 253
    assert re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", name), name


def test_prepuller_is_excluded_from_sandbox_network_policies() -> None:
    """The sandbox NetworkPolicies select `component: sandbox`. The prepuller is
    not a sandbox and must not be swept into that default-deny selector."""
    labels = _prepuller()["spec"]["template"]["metadata"]["labels"]
    assert labels["app.kubernetes.io/component"] == "sandbox-image-prepuller"


def test_prepuller_carries_its_own_deny_all_network_policy() -> None:
    """Being out of the `component: sandbox` selector above means the sandbox
    default-deny doesn't cover it either, which would make this the one
    unrestricted pod in the sandbox namespace. It needs no network — the pull is
    the kubelet's — so it gets its own deny-all instead."""
    docs = list(yaml.safe_load_all(_render(_PREPULLER_TEMPLATE)))
    np = next(d for d in docs if d and d["kind"] == "NetworkPolicy")
    pod_labels = _prepuller()["spec"]["template"]["metadata"]["labels"]

    assert set(np["spec"]["policyTypes"]) == {"Ingress", "Egress"}
    # No `ingress`/`egress` key at all is deny-all for the listed types; an
    # empty-dict rule would be allow-all and is the easy way to get this wrong.
    assert "ingress" not in np["spec"]
    assert "egress" not in np["spec"]
    # Must actually select the prepuller pods.
    assert np["spec"]["podSelector"]["matchLabels"].items() <= pod_labels.items()


def test_prepuller_can_be_disabled() -> None:
    assert _renders_nothing(["--set", "sandboxImagePrepull.enabled=false"])


def test_prepuller_absent_when_craft_disabled() -> None:
    assert _renders_nothing(["--set-string", "configMap.ENABLE_CRAFT=false"])
