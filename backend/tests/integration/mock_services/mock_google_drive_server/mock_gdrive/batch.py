"""Batch requests (`POST /batch/drive/v3`): multipart/mixed, one HTTP request
per part. Each part is a separate call for quotas and stats, as at Google."""

import asyncio
import secrets
from email.message import Message
from email.parser import BytesParser, Parser
from http import HTTPStatus
from urllib.parse import parse_qsl, urlsplit

from .api import ApiRequest, MockGoogleApi
from .responses import MockResponse, bad_request

# Google rejects a batch of more than 100 calls.
MAX_BATCH_PARTS = 100


def _parse_part(part: Message, outer_headers: dict[str, str]) -> ApiRequest | None:
    payload = part.get_payload()
    if not isinstance(payload, str):
        return None
    request_line, _, rest = payload.lstrip("\r\n").partition("\n")
    pieces = request_line.strip().split(" ")
    if len(pieces) < 2:
        return None
    inner = Parser().parsestr(rest)
    headers = {k.lower(): v for k, v in inner.items()}
    if "authorization" not in headers and "authorization" in outer_headers:
        headers["authorization"] = outer_headers["authorization"]
    url = urlsplit(pieces[1])
    return ApiRequest(
        method=pieces[0].upper(),
        path=url.path.lstrip("/"),
        query=dict(parse_qsl(url.query, keep_blank_values=True)),
        headers=headers,
    )


def _response_part(content_id: str, response: MockResponse) -> bytes:
    reason = HTTPStatus(response.status).phrase
    lines = [f"HTTP/1.1 {response.status} {reason}"]
    lines.extend(f"{name}: {value}" for name, value in response.headers.items())
    head = "\r\n".join(
        [
            "Content-Type: application/http",
            f"Content-ID: <response-{content_id.strip('<>')}>",
            "",
            *lines,
            "",
            "",
        ]
    )
    return head.encode() + response.body + b"\r\n"


async def handle_batch(
    api: MockGoogleApi, body: bytes, content_type: str, outer_headers: dict[str, str]
) -> MockResponse:
    message = BytesParser().parsebytes(
        f"Content-Type: {content_type}\r\n\r\n".encode() + body
    )
    if not message.is_multipart():
        return bad_request("The batch request must be multipart/mixed.")
    parts = message.get_payload()
    if not isinstance(parts, list):
        return bad_request("The batch request has no parts.")
    if len(parts) > MAX_BATCH_PARTS:
        return bad_request(f"A batch request accepts at most {MAX_BATCH_PARTS} calls.")
    requests: list[tuple[str, ApiRequest]] = []
    for part in parts:
        if not isinstance(part, Message):
            return bad_request("Invalid batch part.")
        request = _parse_part(part, outer_headers)
        if request is None:
            return bad_request("Invalid batch part.")
        # The Google client folds a long Content-ID over two lines. Google
        # echoes it unfolded, and the client splits it on " + ".
        content_id = " ".join(str(part.get("Content-ID", "")).split())
        requests.append((content_id, request))
    responses = await asyncio.gather(*(api.handle(r) for _, r in requests))
    boundary = f"batch_{secrets.token_hex(12)}"
    out = b""
    for (content_id, _), response in zip(requests, responses, strict=True):
        out += f"--{boundary}\r\n".encode() + _response_part(content_id, response)
    out += f"--{boundary}--\r\n".encode()
    return MockResponse(
        status=200,
        body=out,
        headers={"content-type": f"multipart/mixed; boundary={boundary}"},
    )
