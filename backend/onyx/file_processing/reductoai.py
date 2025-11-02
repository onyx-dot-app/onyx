import mimetypes
import time
from collections.abc import Callable
from typing import Any
from typing import cast
from typing import IO
from typing import Literal
from typing import TYPE_CHECKING

import httpx
from reducto.types.job_get_response import JobGetResponse
from reducto.types.shared.parse_response import ParseResponse
from reducto.types.shared.parse_response import Result
from reducto.types.shared.parse_response import ResultFullResult
from reducto.types.shared.parse_response import ResultFullResultChunkBlock
from reducto.types.shared.parse_response import ResultURLResult

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.configs.constants import KV_REDUCTOAI_API_KEY
from onyx.configs.constants import KV_REDUCTOAI_ENV_KEY
from onyx.file_processing.common import ExtractionResult
from onyx.file_processing.common import get_file_ext
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

if TYPE_CHECKING:
    from reducto.types import (
        ParseRunJobResponse,
    )

logger = setup_logger()

# Defined for mypy checks
EnvironmentLiteral = Literal["production", "eu", "au"]
ChunkModeLiteral = Literal[
    "variable",
    "section",
    "page",
    "disabled",
    "block",
    "page_sections",
]


class ReductoError(Exception):
    """Base exception for Reducto-related errors."""


class ReductoRetryableError(ReductoError):
    """Raised for Reducto operations that should be retried."""


class ReductoNonRetryableError(ReductoError):
    """Raised for Reducto operations that should not be retried."""


def get_reductoai_api_key_and_env() -> tuple[str | None, str | None]:
    kv_store = get_kv_store()
    try:
        key = cast(str, kv_store.load(KV_REDUCTOAI_API_KEY))
        env = cast(str, kv_store.load(KV_REDUCTOAI_ENV_KEY))
        if not env:
            env = "production"
        return key, env
    except KvKeyNotFoundError:
        return None, None


def update_reductoai_api_key_and_env(
    api_key: str | None = None, env: str | None = None
) -> None:
    kv_store = get_kv_store()
    if api_key:
        kv_store.store(KV_REDUCTOAI_API_KEY, api_key)
    if env:
        kv_store.store(KV_REDUCTOAI_ENV_KEY, env)


def delete_reductoai_api_key_and_env() -> None:
    kv_store = get_kv_store()
    kv_store.delete(KV_REDUCTOAI_API_KEY)
    kv_store.delete(KV_REDUCTOAI_ENV_KEY)


def _normalize_reducto_environment(environment: str | None) -> EnvironmentLiteral:
    """Return a Reducto environment literal, defaulting to production."""

    if environment == "eu":
        return "eu"
    if environment == "au":
        return "au"
    return "production"


class ReductoAIExtractor:
    _SUPPORTED_FILE_EXTENSIONS = [
        # Image formats
        ".png",
        ".jpeg",
        ".jpg",
        ".gif",
        ".bmp",
        ".tiff",
        ".pcx",
        ".ppm",
        ".apng",
        ".psd",
        ".cur",
        ".dcx",
        ".ftex",
        ".pixar",
        ".heic",
        # PDF
        ".pdf",
        # Spreadsheets
        ".csv",
        ".xlsx",
        ".xlsm",
        ".xls",
        ".xltx",
        ".xltm",
        ".qpw",
        # Presentations & Text Documents
        ".pptx",
        ".ppt",
        ".docx",
        ".doc",
        ".dotx",
        ".wpd",
        ".txt",
        ".rtf",
    ]

    def extract_with_reductoai(
        self,
        file: IO[Any],
        file_name: str,
        image_callback: Callable[[bytes, str], None] | None = None,
        pdf_pass: str | None = None,
        extract_images: bool = True,
        content_type: str | None = None,
    ) -> ExtractionResult:
        """
        Extract text and images from a file using ReductoAI.

        The Reducto SDK handles async job flow internally for large files,
        so this function appears synchronous to callers.

        Args:
            file: File-like object to process.
            file_name: Name of the file.
            image_callback: Optional callback for streaming images.
            pdf_pass: Optional PDF password.
            extract_images: Whether to extract images from the file.
            content_type: Optional content type of the file.
        Returns:
            ExtractionResult instance, with text and images from the file.

        Raises:
            ReductoError: If processing fails.
        """

        return self._extract_with_reductoai(
            file,
            file_name,
            image_callback,
            pdf_pass,
            "disabled",
            extract_images,
            content_type,
        )[0]

    def _extract_with_reductoai(
        self,
        file: IO[Any],
        file_name: str,
        image_callback: Callable[[bytes, str], None] | None = None,
        pdf_pass: str | None = None,
        chunking: ChunkModeLiteral = "disabled",
        extract_images: bool = True,
        content_type: str | None = None,
    ) -> list[ExtractionResult]:
        """
        NOTE: This may be used directly if/when switching to the reductoai chunking.
        Extract text and images from a file using ReductoAI.

        The Reducto SDK handles async job flow internally for large files,
        so this function appears synchronous to callers.

        Returns one ExtractionResult per chunk, with images from blocks belonging to that chunk.

        Args:
            file: File-like object to process.
            file_name: Name of the file.
            image_callback: Optional callback for streaming images.
            chunking: chunking mode to use. Reducto recommends "variable" as default.
            extract_images: Whether to extract images from the file.
            content_type: Optional content type of the file.
        Returns:
            List of ExtractionResult instances, one per chunk with text and images from that chunk.

        Raises:
            ReductoError: If processing fails.
        """

        # local imports just to reduce memory footprint (similar to unstructured.py)
        from reducto import Reducto

        api_key, env = get_reductoai_api_key_and_env()
        if not api_key:
            raise ValueError("ReductoAI API key not found.")
        environment = _normalize_reducto_environment(env)
        extension = get_file_ext(file_name)
        extension_from_content: str | None = (
            mimetypes.guess_extension(content_type) if content_type else None
        )

        if extension_from_content and extension_from_content != extension:
            # in case the file name does not have a proper extension, or if it does not match
            extension = extension_from_content

        if extension not in ReductoAIExtractor._SUPPORTED_FILE_EXTENSIONS:
            raise ValueError(
                f"File extension {extension} is not supported by ReductoAI."
            )

        client = Reducto(api_key=api_key, environment=environment)
        file.seek(0)

        # NOTE: files over 100 MB will require handling with a signed url upload
        upload_response = client.upload(
            file=file.read(),
            extension=extension if extension else None,
        )
        if not upload_response.file_id:
            raise ValueError("Failed to upload file to ReductoAI.")

        logger.debug(f"Calling Reducto parse on file_id: {upload_response.file_id}")
        response: ParseRunJobResponse = client.parse.run_job(
            input=upload_response.file_id,
            retrieval={
                "chunking": {
                    "chunk_mode": chunking,
                },
            },
            settings={
                "document_password": pdf_pass,
                "return_images": ["figure"] if extract_images else [],
            },
        )

        if not response.job_id:
            raise ValueError("Failed to start parse job with ReductoAI.")

        # Polling for job completion is handled internally by the SDK
        state = "Idle"  # "Pending", "Completed", "Failed", "Idle"
        total_time_limit = 900  # 15 minutes, equals to the default timeout in reductoai
        elapsed_time = 0
        final_response: JobGetResponse | None = None
        while state != "Completed" and state != "Failed":
            final_response = client.job.get(job_id=response.job_id)
            state = final_response.status
            if state in ["Completed", "Failed"]:
                break
            time.sleep(3)
            elapsed_time += 3
            if elapsed_time >= total_time_limit:
                raise ReductoError("ReductoAI parse job timed out.")

        if final_response is None:
            raise ReductoError(
                f"ReductoAI parse job did not return a result. State: {state}"
            )
        if state != "Completed":
            raise ReductoError(
                f"ReductoAI did not complete successfully. State: {state}"
            )

        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as http_client:
            result = self._transform_to_extraction_result(
                final_response,
                http_client=http_client,
                image_callback=image_callback,
            )

        logger.info(
            f"Successfully parsed with Reducto: file={file_name}, "
            f"Chunks={len(result)}"
        )

        return result

    def _transform_to_extraction_result(
        self,
        get_job_response: JobGetResponse,
        http_client: httpx.Client,
        image_callback: Callable[[bytes, str], None] | None = None,
    ) -> list[ExtractionResult]:
        """
        Transform Reducto document result to Onyx ExtractionResult.

        Processes each chunk separately and returns one ExtractionResult per chunk,
        with images from blocks belonging to that specific chunk.

        Args:
            get_job_response: Parsed document from Reducto SDK.
            image_callback: Optional callback for images.
            http_client: Shared HTTP client for fetching remote artifacts.

        Returns:
            List of ExtractionResult instances, one per chunk with text and images from that chunk.
        """

        results: list[ExtractionResult] = []

        result = get_job_response.result

        if isinstance(result, ParseResponse):
            # we only perform parse operations atm
            nested_result = self._get_result(result.result, http_client)

            chunks = nested_result.chunks

            # Process each chunk separately to create one ExtractionResult per chunk
            for chunk_idx, chunk in enumerate(chunks):
                # this is the Markdown text for the whole chunk
                text_content = chunk.content

                # Extract images from blocks for Figure images
                embedded_images: list[tuple[bytes, str]] = []
                for idx, block in enumerate(chunk.blocks):
                    image_bytes, image_name = self._extract_image_from_block(
                        block,
                        idx,
                        http_client,
                    )
                    if image_bytes is not None:
                        embedded_images.append((image_bytes, image_name))
                        if image_callback:
                            try:
                                image_callback(image_bytes, image_name)
                            except Exception as e:
                                logger.error(
                                    f"Image callback failed for {image_name}: {e}"
                                )

                metadata = {
                    "source": "reductoai",
                    "job_id": result.job_id,
                }

                extraction_result = ExtractionResult(
                    text_content=text_content,
                    embedded_images=embedded_images,
                    metadata=metadata,
                )
                results.append(extraction_result)

        return results

    def _get_result(
        self, result: Result, http_client: httpx.Client
    ) -> ResultFullResult:
        """
        From the docs:
        The response from the document processing service. Note that there
        can be two types of responses, Full Result and URL Result. This is
        due to limitations on the max return size on HTTPS. If the response
        is too large, it will be returned as a presigned URL in the URL
        response. You should handle this in your application.
        """

        if isinstance(result, ResultFullResult):
            return result
        elif isinstance(result, ResultURLResult):
            return self._download_reducto_result(http_client, result.url)
        else:
            raise ValueError(f"Unsupported parse response type: {type(result)}")

    @retry_builder(
        tries=6,
        delay=1,
        backoff=2,
        max_delay=30,
        exceptions=(ReductoRetryableError, httpx.RequestError),
    )
    def _download_reducto_result(
        self, http_client: httpx.Client, url: str
    ) -> ResultFullResult:
        """Download the result payload from the presigned URL."""

        try:
            response = http_client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status is not None and 500 <= status < 600:
                raise ReductoRetryableError(
                    f"Reducto result download failed with status {status}"
                ) from exc
            raise ReductoNonRetryableError(
                f"Reducto result download failed with status {status}"
            ) from exc
        except httpx.RequestError:
            raise

        return ResultFullResult.model_validate(response.json())

    def _extract_image_from_block(
        self,
        block: ResultFullResultChunkBlock,
        block_idx: int,
        http_client: httpx.Client,
    ) -> tuple[bytes | None, str]:
        # Only Figure images are interesting atm
        if block.type == "Figure" and block.image_url is not None:
            try:
                image_bytes = self._download_image(http_client, block.image_url)
            except (
                ReductoRetryableError,
                ReductoNonRetryableError,
                httpx.RequestError,
            ) as exc:
                logger.warning(f"Failed to download image {block_idx}: {exc}")
                return None, ""
            page_num = block.bbox.page
            image_name = f"page_{page_num}_{block_idx}.png"
            return image_bytes, image_name
        return None, ""

    @retry_builder(
        tries=6,
        delay=1,
        backoff=2,
        max_delay=30,
        exceptions=(ReductoRetryableError, httpx.RequestError),
    )
    def _download_image(self, http_client: httpx.Client, image_url: str) -> bytes:
        """
        These urls are aws S3 presigned urls.
        Content-Type: binary/octet-stream, but .png in practice.
        """

        try:
            response = http_client.get(image_url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status is not None and 500 <= status < 600:
                raise ReductoRetryableError(
                    f"Reducto image download failed with status {status}"
                ) from exc
            raise ReductoNonRetryableError(
                f"Reducto image download failed with status {status}"
            ) from exc
        except httpx.RequestError:
            raise

        return response.content
