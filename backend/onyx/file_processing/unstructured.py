from typing import Any, IO, cast
import requests
from unstructured.staging.base import dict_to_elements
from onyx.configs.constants import KV_UNSTRUCTURED_API_KEY
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Keep API key functions if used elsewhere in your application
def get_unstructured_api_key() -> str | None:
    kv_store = get_kv_store()
    try:
        return cast(str, kv_store.load(KV_UNSTRUCTURED_API_KEY))
    except KvKeyNotFoundError:
        return None

def update_unstructured_api_key(api_key: str) -> None:
    kv_store = get_kv_store()
    kv_store.store(KV_UNSTRUCTURED_API_KEY, api_key)

def delete_unstructured_api_key() -> None:
    kv_store = get_kv_store()
    kv_store.delete(KV_UNSTRUCTURED_API_KEY)

def unstructured_to_text(file: IO[Any], file_name: str) -> str:
    logger.debug(f"Starting to process file: {file_name}")
    
    # Local Docker container endpoint (update port if different)
    UNSTRUCTURED_ENDPOINT = "http://localhost:8000/general/v0/general"
    
    # Reset file pointer and prepare for upload
    file.seek(0)
    files = {"files": (file_name, file)}
    data = {"strategy": "fast"}

    try:
        # Send request to local Docker container
        response = requests.post(
            UNSTRUCTURED_ENDPOINT,
            files=files,
            data=data,
            timeout=30  # Adjust timeout as needed
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error processing {file_name}: {str(e)}")
        raise

    # Handle HTTP errors
    if response.status_code != 200:
        err = f"Unstructured API error ({response.status_code}): {response.text}"
        logger.error(err)
        raise RuntimeError(err)

    try:
        # Parse response elements
        elements = dict_to_elements(response.json()["elements"])
        return "\n\n".join(str(el) for el in elements)
    except (KeyError, ValueError) as e:
        logger.error(f"Error parsing response for {file_name}: {str(e)}")
        raise
