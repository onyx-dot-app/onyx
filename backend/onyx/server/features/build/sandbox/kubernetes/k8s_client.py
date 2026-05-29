import os

from kubernetes import config

from onyx.utils.logger import setup_logger

logger = setup_logger()


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
