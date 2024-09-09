import requests
from retry import retry

from danswer.utils.logger import setup_logger
from shared_configs.configs import INDEXING_MODEL_SERVER_HOST
from shared_configs.configs import INDEXING_MODEL_SERVER_PORT
from shared_configs.configs import MODEL_SERVER_HOST
from shared_configs.configs import MODEL_SERVER_PORT

logger = setup_logger()


@retry(tries=5, delay=5)
def gpu_status_request(indexing: bool = True) -> bool:
    if indexing:
        model_server_url = f"{INDEXING_MODEL_SERVER_HOST}:{INDEXING_MODEL_SERVER_PORT}"
    else:
        model_server_url = f"{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT}"

    if "http" not in model_server_url:
        model_server_url = f"http://{model_server_url}"

    try:
        response = requests.get(f"{model_server_url}/api/gpu-status", timeout=10)
        response.raise_for_status()
        gpu_status = response.json()
        return gpu_status["gpu_available"]
    except requests.RequestException as e:
        logger.error(f"Error: Unable to fetch GPU status. Error: {str(e)}")
        raise  # Re-raise exception to trigger a retry
