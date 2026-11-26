"""The byte protocol of the chat VM's browser service (guest vsock port
BROWSER_SERVICE_PORT, reached through the host agent's Dial).

Each message: a 4-byte big-endian length N of the rest, one kind byte, then
N-1 payload bytes. A JSON message is one UTF-8 JSON object; a JPEG message is
one frame of a viewer stream. The first message from the client is a JSON
hello: an agent call (`call_hello`), which gets one JSON answer
(`BrowserCallResponse`) before the service closes, or a viewer (`view_hello`),
which streams until either side closes. The service source:
`deployment/craft-runtime/browser-service/`.
"""

import json
import struct
from enum import IntEnum

from pydantic import BaseModel, ConfigDict, JsonValue

# The guest daemon relays this vsock port to the browser service.
BROWSER_SERVICE_PORT = 3011
# The browser service protocol that this client speaks; BrowserStart
# reports the one the daemon relays (0: none).
BROWSER_SERVICE_PROTOCOL = 1
# Largest N (kind byte and payload). A larger length closes the connection.
MAX_FRAME_BYTES = 16 << 20
_HEADER = struct.Struct(">I")


class FrameKind(IntEnum):
    JSON = 1
    JPEG = 2


class BrowserFrame(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: FrameKind
    payload: bytes


class BrowserFramingError(Exception):
    """The peer broke the framing; close the connection."""


def encode_frame(frame: BrowserFrame) -> bytes:
    size = len(frame.payload) + 1
    if size > MAX_FRAME_BYTES:
        raise BrowserFramingError(f"a {size}-byte message is over the limit")
    return _HEADER.pack(size) + bytes([frame.kind]) + frame.payload


def json_frame(message: dict[str, JsonValue]) -> BrowserFrame:
    return BrowserFrame(
        kind=FrameKind.JSON,
        payload=json.dumps(message, separators=(",", ":")).encode(),
    )


def parse_json_frame(frame: BrowserFrame) -> dict[str, JsonValue]:
    """The JSON object of a JSON frame."""
    if frame.kind is not FrameKind.JSON:
        raise BrowserFramingError(f"expected a JSON message, got kind {frame.kind}")
    try:
        message = json.loads(frame.payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BrowserFramingError(f"bad JSON message: {e}") from e
    if not isinstance(message, dict):
        raise BrowserFramingError("a JSON message must be an object")
    return message


class FrameDecoder:
    """Splits a byte stream into frames. Not thread-safe."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[BrowserFrame]:
        """The frames that `data` completes, in order."""
        self._buffer += data
        frames: list[BrowserFrame] = []
        while len(self._buffer) >= _HEADER.size:
            (size,) = _HEADER.unpack_from(self._buffer)
            if size == 0 or size > MAX_FRAME_BYTES:
                raise BrowserFramingError(f"bad message length {size}")
            end = _HEADER.size + size
            if len(self._buffer) < end:
                break
            kind_byte = self._buffer[_HEADER.size]
            try:
                kind = FrameKind(kind_byte)
            except ValueError as e:
                raise BrowserFramingError(f"unknown message kind {kind_byte}") from e
            frames.append(
                BrowserFrame(
                    kind=kind, payload=bytes(self._buffer[_HEADER.size + 1 : end])
                )
            )
            del self._buffer[:end]
        return frames

    @property
    def pending_bytes(self) -> int:
        """Bytes of a message that has not ended yet."""
        return len(self._buffer)


def call_hello(
    chat_session_id: str, method: str, params: dict[str, JsonValue]
) -> BrowserFrame:
    return json_frame(
        {"op": "call", "chat": chat_session_id, "method": method, "params": params}
    )


def view_hello(chat_session_id: str) -> BrowserFrame:
    return json_frame({"op": "view", "chat": chat_session_id})


class BrowserCallError(BaseModel):
    message: str


class BrowserCallResponse(BaseModel):
    """The service's one answer to an agent call."""

    ok: bool
    result: dict[str, JsonValue] | None = None
    error: BrowserCallError | None = None
