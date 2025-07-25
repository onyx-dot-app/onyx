from enum import Enum
from typing import Any
from typing import IO

import requests
from reducto import Reducto
from unstructured.staging.base import dict_to_elements
from unstructured_client import UnstructuredClient  # type: ignore
from unstructured_client.models import operations  # type: ignore
from unstructured_client.models import shared

from onyx.configs.constants import DOC_PROCESSING_API_KEY
from onyx.configs.constants import DOC_PROCESSING_TYPE
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.utils.logger import setup_logger

logger = setup_logger()


class DocumentProcessor(Enum):
    UNSTRUCTURED = "unstructured"
    REDUCTO = "reducto"


def get_api_key() -> str | None:
    kv_store = get_kv_store()
    try:
        docprocessing_type = kv_store.load(DOC_PROCESSING_TYPE)
        if docprocessing_type:
            return (docprocessing_type, kv_store.load(DOC_PROCESSING_API_KEY))
        else:
            return None
    except KvKeyNotFoundError:
        return None


def update_api_key(documentProcessor: DocumentProcessor, api_key: str) -> None:
    kv_store = get_kv_store()
    kv_store.store(DOC_PROCESSING_TYPE, documentProcessor.value)
    kv_store.store(DOC_PROCESSING_API_KEY, api_key)


def delete_api_key(documentProcessor: DocumentProcessor) -> None:
    kv_store = get_kv_store()
    kv_store.delete(DOC_PROCESSING_TYPE)
    kv_store.delete(DOC_PROCESSING_API_KEY)


def _sdk_partition_request(
    file: IO[Any], file_name: str, **kwargs: Any
) -> operations.PartitionRequest:
    file.seek(0, 0)
    try:
        request = operations.PartitionRequest(
            partition_parameters=shared.PartitionParameters(
                files=shared.Files(content=file.read(), file_name=file_name),
                **kwargs,
            ),
        )
        return request
    except Exception as e:
        logger.error(f"Error creating partition request for file {file_name}: {str(e)}")
        raise


def unstructured_to_text(file: IO[Any], file_name: str, api_key: str) -> str:
    logger.debug(f"Starting to read file: {file_name}")
    req = _sdk_partition_request(file, file_name, strategy="fast")

    unstructured_client = UnstructuredClient(api_key_auth=api_key)

    response = unstructured_client.general.partition(req)  # type: ignore
    elements = dict_to_elements(response.elements)

    if response.status_code != 200:
        err = f"Received unexpected status code {response.status_code} from Unstructured API."
        logger.error(err)
        raise ValueError(err)

    return "\n\n".join(str(el) for el in elements)


def reducto_to_text(file: IO[Any], file_name: str, api_key: str) -> str:
    logger.debug(f"Starting to read file with reducto: {file_name}")
    client = Reducto(api_key=api_key)

    # get file size
    current_pos = file.tell()
    file.seek(0, 2)
    file_size_bytes = file.tell()
    file.seek(current_pos)
    file_size_mb = file_size_bytes / (1024 * 1024)

    if file_size_mb < 95:
        # Use direct upload for smaller files
        upload = client.upload(file=file)
        response = client.parse.run(document_url=upload)
        logger.debug(response)

    else:
        # untested presigned URL upload method for larger files
        logger.debug(
            f"File {file_name} is {file_size_mb:.2f}MB, using presigned URL upload"
        )

        presigned_response = client.upload.presigned_url(file_name=file_name)
        presigned_url = presigned_response["presigned_url"]
        document_id = presigned_response["document_id"]

        file.seek(0)  # reset file pointer
        files = {"file": (file_name, file, "application/octet-stream")}
        upload_response = requests.post(presigned_url, files=files)
        upload_response.raise_for_status()

        response = client.parse.run(document_id=document_id)
    chunks = response.result.chunks
    content_parts = []
    for chunk in chunks:
        if hasattr(chunk, "content") and chunk.content:
            content_parts.append(chunk.content)

    return "\n\n".join(content_parts)
