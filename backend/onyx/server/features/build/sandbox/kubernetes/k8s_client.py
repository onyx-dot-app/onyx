import os

from kubernetes import client
from kubernetes import config
from urllib3.util.retry import Retry

from onyx.utils.logger import setup_logger

logger = setup_logger()

# (connect, read) deadline for synchronous boot-time API calls. The in-cluster
# client has no default per-request deadline, so on a half-open apiserver socket
# it blocks until the kernel's TCP retransmission limit (minutes) — turning a
# transient hiccup into a crash loop. Every boot call must pass this.
K8S_BOOT_REQUEST_TIMEOUT_S: tuple[float, float] = (5.0, 15.0)

_BOOT_CONNECT_RETRIES = 2


def load_kube_config() -> None:
    try:
        config.load_incluster_config()
        logger.info("loaded in-cluster Kubernetes config")
        return
    except config.ConfigException:
        pass

    # Optional override for dev: pin to a specific kubeconfig context
    # so the api_server targets the right cluster regardless of the
    # developer's `kubectl config current-context` (e.g. a stray EKS
    # context selected for unrelated work).
    context = os.environ.get("K8S_CONTEXT") or None

    try:
        config.load_kube_config(context=context)
        logger.info(
            "loaded kubeconfig from default location (context=%s)",
            context or "<current-context>",
        )
    except config.ConfigException as e:
        raise RuntimeError(f"Failed to load Kubernetes configuration: {e}") from e


def build_core_v1_api() -> client.CoreV1Api:
    """CoreV1Api whose transport retries dropped connections, for boot-time use.

    Callers must still pass `_request_timeout=K8S_BOOT_REQUEST_TIMEOUT_S` on each
    synchronous boot call; the client has no default per-request deadline.
    """
    load_kube_config()
    configuration = client.Configuration.get_default_copy()
    # Connect-only retries: a failed connect means the request never reached the
    # server, so replaying it can't double-execute a create.
    configuration.retries = Retry(
        total=_BOOT_CONNECT_RETRIES,
        connect=_BOOT_CONNECT_RETRIES,
        read=0,
        backoff_factor=0.5,
    )
    return client.CoreV1Api(client.ApiClient(configuration))
