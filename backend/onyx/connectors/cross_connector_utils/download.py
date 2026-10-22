import requests

from onyx.utils.logger import setup_logger

logger = setup_logger()

_DOWNLOAD_CHUNK_SIZE = 1024 * 1024


def download_file(
    url: str, *, max_size_bytes: int, timeout_seconds: float
) -> bytes | None:
    with requests.get(url, timeout=timeout_seconds, stream=True) as response:
        response.raise_for_status()
        chunks: list[bytes] = []
        downloaded: int = 0
        chunk_size: int = max(1, min(_DOWNLOAD_CHUNK_SIZE, max_size_bytes + 1))
        for chunk in response.iter_content(chunk_size=chunk_size):
            if not chunk:
                continue
            downloaded += len(chunk)
            if downloaded > max_size_bytes:
                logger.warning(
                    "Skipping download: body exceeds %s bytes", max_size_bytes
                )
                return None
            chunks.append(chunk)
        return b"".join(chunks)
