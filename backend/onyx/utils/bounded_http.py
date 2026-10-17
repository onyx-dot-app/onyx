import threading

import requests
import urllib3

_BODY_CHUNK_SIZE = 64 * 1024


class BoundedBodyError(Exception):
    """The response body was abandoned before it was fully read."""


class ResponseTooLargeError(BoundedBodyError):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"response body exceeds {max_bytes} bytes")
        self.max_bytes = max_bytes


class ResponseBodyTimeoutError(BoundedBodyError):
    def __init__(self, deadline_seconds: float) -> None:
        super().__init__(f"response body took longer than {deadline_seconds}s")
        self.deadline_seconds = deadline_seconds


def read_bounded_body(
    response: requests.Response, *, max_bytes: int, deadline_seconds: float
) -> bytes:
    """Read the decoded body of a ``stream=True`` response, stopping once it
    exceeds ``max_bytes`` or the wall-clock deadline passes.

    Raises ``ResponseTooLargeError`` or ``ResponseBodyTimeoutError``.
    """
    declared = response.headers.get("Content-Length")
    if declared is not None and declared.isdigit() and int(declared) > max_bytes:
        raise ResponseTooLargeError(max_bytes)

    deadline_hit = threading.Event()

    def _on_deadline() -> None:
        deadline_hit.set()
        # Shutting down the read side ends a read blocked on a stalled server.
        try:
            response.raw.shutdown()
        except Exception:
            pass

    timer = threading.Timer(deadline_seconds, _on_deadline)
    timer.daemon = True
    timer.start()
    chunks: list[bytes] = []
    total = 0
    try:
        # read1 returns what is available; urllib3 bounds decoded output.
        while chunk := response.raw.read1(_BODY_CHUNK_SIZE, decode_content=True):
            if deadline_hit.is_set():
                break
            total += len(chunk)
            if total > max_bytes:
                raise ResponseTooLargeError(max_bytes)
            chunks.append(chunk)
    except urllib3.exceptions.HTTPError:
        if not deadline_hit.is_set():
            raise
    finally:
        timer.cancel()
    if deadline_hit.is_set():
        raise ResponseBodyTimeoutError(deadline_seconds)
    return b"".join(chunks)
