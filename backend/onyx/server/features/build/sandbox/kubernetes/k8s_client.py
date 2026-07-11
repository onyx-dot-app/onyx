import os
from typing import Any

from kubernetes import client
from kubernetes import config
from urllib3.util.retry import Retry

from onyx.utils.logger import setup_logger

logger = setup_logger()

# (connect, read) deadline applied to every request made through the boot client.
# The kubernetes client has no Configuration-level request timeout, so on a
# half-open apiserver socket a call blocks until the kernel's TCP retransmission
# limit (minutes) — turning a transient hiccup into a crash loop.
_REQUEST_TIMEOUT_S: tuple[float, float] = (5.0, 15.0)

_BOOT_CONNECT_RETRIES = 2


class _DeadlinedApiClient(client.ApiClient):
    """ApiClient that applies `_REQUEST_TIMEOUT_S` to any call that omits one.

    Configuring the deadline here (rather than at every call site) means callers
    can't forget it, and there is no other place to set it: the kubernetes client
    exposes no Configuration-level request timeout.
    """

    def request(self, *args: Any, _request_timeout: Any = None, **kwargs: Any) -> Any:
        if _request_timeout is None:
            _request_timeout = _REQUEST_TIMEOUT_S
        return super().request(*args, _request_timeout=_request_timeout, **kwargs)


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
    """CoreV1Api for boot-time use: per-request deadline + connect retries.

    Every request gets `_REQUEST_TIMEOUT_S` (see `_DeadlinedApiClient`) so a
    stalled connection fails fast instead of blocking for minutes.
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
    return client.CoreV1Api(_DeadlinedApiClient(configuration))
