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

Lives beside ``test_pod_spec.py`` in the ``craft_helm`` shard, the lane that
provides ``helm`` and runs ``helm dependency build`` (see
``pr-external-dependency-unit-tests.yml``). Skips locally when those are
unavailable; in CI those conditions fail instead of masking the suite.

Only a missing-dependency error is treated as "can't run here". Any other helm
failure is the chart being broken and fails the test — a render test that
reports a broken chart as a skip is worse than no test.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import NoReturn

import pytest
import yaml

from tests.common.paths import find_ancestor_containing

_REPO_ROOT = find_ancestor_containing("deployment/helm/charts/onyx")
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


def _skip_or_fail(reason: str) -> NoReturn:
    """Skip locally, but fail in CI — a shard that renders nothing must not
    report green."""
    if os.environ.get("CI"):
        pytest.fail(reason)
    pytest.skip(reason)


def _handle_render_failure(stderr: str) -> NoReturn:
    """A missing-deps error means we can't run here; anything else is a real
    chart defect and must not be laundered into a skip."""
    if any(marker in stderr for marker in _MISSING_DEPS_MARKERS):
        _skip_or_fail(f"chart dependencies not built: {stderr.strip()}")
    pytest.fail(f"helm template failed: {stderr.strip()}")


def _run_helm(
    template: str, extra_args: list[str] | None = None
) -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    if helm is None:
        _skip_or_fail("helm binary not available")
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
    """The DaemonSet. The template also emits a NetworkPolicy, so select by kind
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


def _rendered_kinds(extra_args: list[str] | None = None) -> list[str]:
    docs = yaml.safe_load_all(_render(_PREPULLER_TEMPLATE, extra_args))
    return [d["kind"] for d in docs if d]


# Objects with no `metadata.namespace`. A cluster-scoped object from this
# template is what broke the deploy described in
# test_prepuller_ships_no_cluster_scoped_objects.
_CLUSTER_SCOPED_KINDS = {
    "PriorityClass",
    "ClusterRole",
    "ClusterRoleBinding",
    "StorageClass",
    "Namespace",
    "CustomResourceDefinition",
    "PersistentVolume",
}


def test_prepuller_ships_no_cluster_scoped_objects() -> None:
    """Regression for a broken `helm upgrade` (#13490).

    The prepuller originally created its own PriorityClass at value -10. A
    follow-up changed the default to -11 while keeping the object's name, and
    every existing install failed to upgrade:

        Error: UPGRADE FAILED: cannot patch
        "onyx-onyx-sandbox-image-prepuller" with kind PriorityClass: ...
        value: Forbidden: may not be changed in an update.

    `PriorityClass.value` is immutable and `helm upgrade` patches, so that field
    could never be changed in place — and because Helm aborts the whole release
    on one rejected patch, a latency optimisation took down the nightly deploy
    of everything else.

    The class was removed rather than worked around: it bought very little (see
    docs/craft/sandbox/image-and-spinup.md), and an operator who wants one
    points `priorityClassName` at their own. Keep this template namespaced —
    cluster-scoped objects also collide between releases sharing a name in
    different namespaces, which is why the removed class needed a
    namespace-hashed name in the first place.
    """
    assert not _CLUSTER_SCOPED_KINDS.intersection(_rendered_kinds())


def test_prepuller_has_no_priority_class_name_by_default() -> None:
    """The chart creates no class, so it must not name one either — a
    `priorityClassName` pointing at a nonexistent class fails pod admission."""
    assert "priorityClassName" not in _prepuller_pod_spec()


def test_prepuller_can_run_under_an_operator_supplied_priority_class() -> None:
    """The opt-in for anyone who does want the prepuller preemptible: name an
    existing class, and it is used verbatim without the chart creating one."""
    args = ["--set", "sandboxImagePrepull.priorityClassName=system-node-critical"]

    assert "PriorityClass" not in _rendered_kinds(args)
    assert _prepuller_pod_spec(args)["priorityClassName"] == "system-node-critical"


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


def test_prepuller_object_names_stay_within_k8s_limits() -> None:
    """A long release/namespace pair must still emit valid names. Namespaced
    objects don't need the namespace hashed into them the way the removed
    PriorityClass did, but they do still have to be DNS-1123."""
    docs = [
        d
        for d in yaml.safe_load_all(
            _render(_PREPULLER_TEMPLATE, ["--namespace", "a" * 60])
        )
        if d
    ]
    assert docs
    for doc in docs:
        name = doc["metadata"]["name"]
        assert len(name) <= 253, name
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
