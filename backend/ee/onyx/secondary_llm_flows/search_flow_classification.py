import requests

from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time
from shared_configs.configs import MODEL_SERVER_HOST
from shared_configs.configs import MODEL_SERVER_PORT
from shared_configs.model_server_models import SearchChatClassificationRequest
from shared_configs.model_server_models import SearchChatClassificationResponse

logger = setup_logger()


def build_model_server_url(host: str, port: int) -> str:
    """Build the model server URL from host and port."""
    return f"http://{host}:{port}"


@log_function_time(print_only=True)
def classify_is_search_flow(
    query: str,
    model_server_host: str = MODEL_SERVER_HOST,
    model_server_port: int = MODEL_SERVER_PORT,
) -> bool:
    """
    Classify whether a query is better suited for search or chat mode
    using the HuggingFace search-chat classifier model.

    Args:
        query: The user's query to classify
        model_server_host: Host of the model server
        model_server_port: Port of the model server

    Returns:
        bool: True if query should use search flow, False for chat flow
    """
    model_server_url = build_model_server_url(model_server_host, model_server_port)
    endpoint = f"{model_server_url}/classifier/search-chat"

    request = SearchChatClassificationRequest(query=query)

    try:
        response = requests.post(
            endpoint,
            json=request.model_dump(),
            timeout=5,  # 5 second timeout for model inference
        )
        response.raise_for_status()

        result = SearchChatClassificationResponse(**response.json())

        logger.debug(
            f"Search flow classification: is_search={result.is_search} "
            f"confidence={result.confidence:.3f}"
        )

        return result.is_search

    except requests.exceptions.Timeout:
        logger.warning("Search flow classification timed out; defaulting to chat flow.")
        return False
    except requests.exceptions.RequestException as e:
        logger.warning(
            f"Search flow classification request failed: {e}; defaulting to chat flow."
        )
        return False
    except Exception as e:
        logger.warning(
            f"Search flow classification failed: {e}; defaulting to chat flow."
        )
        return False
