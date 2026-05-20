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

    try:
        config.load_kube_config()
        logger.info("loaded kubeconfig from default location")
    except config.ConfigException as e:
        raise RuntimeError(f"Failed to load Kubernetes configuration: {e}") from e
