"""The pod spec and the Docker create arguments of harness sandboxes."""

from unittest.mock import MagicMock
from uuid import uuid4

from kubernetes import client

from onyx.server.features.build.sandbox.container.docker_runtime import (
    build_harness_container_kwargs,
)
from onyx.server.features.build.sandbox.container.models import ContainerSpec
from onyx.server.features.build.sandbox.container.pod_runtime import (
    PodRuntime,
    daemon_secret_name,
)
from onyx.server.features.build.sandbox.labels import (
    LABEL_DOCKER_COMPONENT,
    LABEL_DOCKER_NETWORK,
    LABEL_K8S_COMPONENT,
    LABEL_PROVISIONING_ATTEMPT,
    LABEL_SANDBOX_ID,
    LABEL_SANDBOX_KIND,
    LABEL_TENANT_ID,
    is_harness_resource,
)

_DAEMON_ARGS = [
    "--listen",
    "tcp:0.0.0.0:8052",
    "--key-file",
    "/run/craft-fc/daemon/key",
    "--tls-cert",
    "/run/craft-fc/daemon/tls.crt",
    "--tls-key",
    "/run/craft-fc/daemon/tls.key",
]


def _spec() -> ContainerSpec:
    sandbox_id = uuid4()
    return ContainerSpec(
        tenant_id="tenant_a",
        sandbox_id=sandbox_id,
        attempt=3,
        name=f"harness-{sandbox_id}-3",
    )


def _template() -> client.V1PodTemplate:
    return client.V1PodTemplate(
        metadata=client.V1ObjectMeta(name="harness-sandbox-pod"),
        template=client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(
                labels={LABEL_K8S_COMPONENT: "sandbox", "from-template": "yes"}
            ),
            spec=client.V1PodSpec(
                runtime_class_name="gvisor",
                restart_policy="Never",
                init_containers=[
                    client.V1Container(name="sandbox-init", image="img:container")
                ],
                containers=[
                    client.V1Container(
                        name="sandbox",
                        image="img:container",
                        volume_mounts=[
                            client.V1VolumeMount(name="ca", mount_path="/sandbox-ca")
                        ],
                    )
                ],
                volumes=[client.V1Volume(name="ca")],
            ),
        ),
    )


def test_the_pod_overlay_sets_the_daemon_contract() -> None:
    core_api = MagicMock(spec=client.CoreV1Api)
    core_api.read_namespaced_pod_template.return_value = _template()
    runtime = PodRuntime(
        core_api=core_api,
        namespace="sandboxes",
        template_name="harness-sandbox-pod",
        proxy_host="10.0.0.9",
    )
    spec = _spec()

    pod = runtime.build_pod(spec)

    labels = pod.metadata.labels
    assert labels["from-template"] == "yes"
    assert labels[LABEL_SANDBOX_ID] == str(spec.sandbox_id)
    assert labels[LABEL_TENANT_ID] == "tenant_a"
    assert labels[LABEL_PROVISIONING_ATTEMPT] == "3"
    assert is_harness_resource(labels)
    assert pod.metadata.name == spec.name
    assert pod.metadata.namespace == "sandboxes"

    pod_spec = pod.spec
    # The template keeps scheduling and the runtime class; the overlay owns
    # the restart policy and the proxy hostAlias.
    assert pod_spec.runtime_class_name == "gvisor"
    assert pod_spec.restart_policy == "Always"
    assert pod_spec.automount_service_account_token is False
    [alias] = pod_spec.host_aliases
    assert alias.ip == "10.0.0.9" and alias.hostnames == ["sandbox-proxy"]

    [daemon] = pod_spec.containers
    assert daemon.command == ["/usr/local/bin/sandbox-entrypoint"]
    assert daemon.args == _DAEMON_ARGS
    assert [p.container_port for p in daemon.ports] == [8052]
    assert daemon.readiness_probe.tcp_socket.port == 8052
    assert daemon.resources.requests == {
        "cpu": "1000m",
        "memory": "2Gi",
        "ephemeral-storage": "5Gi",
    }
    assert daemon.resources.limits == {
        "cpu": "2000m",
        "memory": "10Gi",
        "ephemeral-storage": "20Gi",
    }
    mounts = {m.name: m for m in daemon.volume_mounts}
    assert mounts["ca"].mount_path == "/sandbox-ca"
    assert mounts["daemon-files"].mount_path == "/run/craft-fc/daemon"
    assert mounts["daemon-files"].read_only is True
    assert mounts["workspaces"].mount_path == "/home/onyx/workspaces"
    volumes = {v.name: v for v in pod_spec.volumes}
    assert volumes["workspaces"].empty_dir is not None
    secret = volumes["daemon-files"].secret
    assert secret.secret_name == daemon_secret_name(spec.name)
    assert secret.default_mode == 0o440
    assert {item.key for item in secret.items} == {"key", "tls.crt", "tls.key"}

    # The template object stays unchanged for the next pod.
    template_spec = core_api.read_namespaced_pod_template.return_value.template.spec
    assert template_spec.restart_policy == "Never"
    assert template_spec.containers[0].args is None


def test_the_docker_container_is_hardened_and_labeled() -> None:
    spec = _spec()

    kwargs = build_harness_container_kwargs(
        spec,
        image="img:container",
        network="onyx_craft_sandbox",
        proxy_host="sandbox-proxy",
        proxy_ca_volume="sandbox_proxy_ca",
        memory_limit="2g",
        cpu_limit=1.5,
        pids_limit=2048,
        oci_runtime="",
        publish_daemon_port=False,
        compose_project="onyx",
    )

    assert kwargs["name"] == spec.name
    assert kwargs["entrypoint"] == ["/usr/local/bin/firewall-init"]
    assert kwargs["command"] == ["/usr/local/bin/sandbox-entrypoint", *_DAEMON_ARGS]
    assert kwargs["user"] == "0:0"
    assert kwargs["cap_drop"] == ["ALL"]
    assert sorted(kwargs["cap_add"]) == [
        "CHOWN",
        "NET_ADMIN",
        "SETGID",
        "SETPCAP",
        "SETUID",
    ]
    assert kwargs["security_opt"] == ["no-new-privileges:true"]
    assert kwargs["privileged"] is False
    assert kwargs["network"] == "onyx_craft_sandbox"
    assert kwargs["mem_limit"] == "2g"
    assert kwargs["nano_cpus"] == 1_500_000_000
    assert kwargs["pids_limit"] == 2048
    assert kwargs["restart_policy"] == {"Name": "unless-stopped"}
    assert "runtime" not in kwargs
    assert "ports" not in kwargs
    # Only the proxy CA, read-only: no Docker socket, no host paths.
    assert kwargs["volumes"] == {
        "sandbox_proxy_ca": {"bind": "/sandbox-ca", "mode": "ro"}
    }
    env = kwargs["environment"]
    assert env["SANDBOX_PROXY_HOST"] == "sandbox-proxy"
    assert env["SANDBOX_PROXY_BOOTSTRAP_MODE"] == "entrypoint"
    assert env["HTTPS_PROXY"].startswith("http://sandbox-proxy:")
    labels = kwargs["labels"]
    assert labels[LABEL_DOCKER_COMPONENT] == "craft-sandbox"
    assert labels[LABEL_DOCKER_NETWORK] == "onyx_craft_sandbox"
    assert labels[LABEL_SANDBOX_KIND] == "harness"
    assert labels[LABEL_PROVISIONING_ATTEMPT] == "3"
    assert labels["com.docker.compose.project"] == "onyx"


def test_docker_options_for_gvisor_and_host_run_dev() -> None:
    kwargs = build_harness_container_kwargs(
        _spec(),
        image="img:container",
        network="net",
        proxy_host="sandbox-proxy",
        proxy_ca_volume="ca",
        memory_limit="2g",
        cpu_limit=1.0,
        pids_limit=512,
        oci_runtime="runsc",
        publish_daemon_port=True,
        compose_project=None,
    )

    assert kwargs["runtime"] == "runsc"
    assert kwargs["ports"] == {"8052/tcp": ("127.0.0.1", None)}
    assert "com.docker.compose.project" not in kwargs["labels"]
