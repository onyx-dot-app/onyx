"""Sender builders and fake delivery transports for fleet telemetry tests."""

import gzip
import io
import json
from collections.abc import Mapping
from typing import Any
from unittest.mock import patch

from onyx.utils import fleet_telemetry
from onyx.utils.fleet_telemetry import BoundedTelemetry

TEST_KEY: str = "a" * 64
# What the fleet service answers to `/v1/enroll`.
TEST_ENROLLMENT: dict[str, str] = {
    "customer_uuid": "11111111-1111-4111-8111-111111111111",
    "deployment_id": "auto-11111111111141118111111111111111",
}


class Response:
    """The parts of a streamed `requests.Response` that telemetry reads."""

    def __init__(self, result: object, status: int = 200) -> None:
        self.ok: bool = 200 <= status < 300
        self.status_code: int = status
        self.headers: dict[str, str] = {}
        self.raw: io.BytesIO = io.BytesIO(json.dumps(result).encode())

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *args: object) -> None:
        self.raw.close()


def make_sender(*, capacity: int = 16, report_process: bool = True) -> BoundedTelemetry:
    """An enrolled sender with no delivery thread. Tests deliver with `flush_once`."""
    sender: BoundedTelemetry = BoundedTelemetry(
        "api", capacity=capacity, report_process=report_process
    )
    with patch.object(fleet_telemetry, "deployment_key", return_value=TEST_KEY):
        sender._enroll(lambda *_args, **_kwargs: Response(TEST_ENROLLMENT))
    return sender


def posted_events(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The events in the gzip JSON body of one delivery request."""
    return json.loads(gzip.decompress(request["data"]))["events"]


def accept_all(url: str, **kwargs: Any) -> Response:
    """A delivery transport that enrolls and accepts every event of the request."""
    if url.endswith("/v1/enroll"):
        return Response(TEST_ENROLLMENT)
    events: list[dict[str, Any]] = posted_events(kwargs)
    return Response(
        {
            "results": [{"index": i, "status": "accepted"} for i in range(len(events))],
            "accepted": len(events),
            "rejected": 0,
        }
    )


class RecordingTransport:
    """Accepts every event, like `accept_all`, and keeps the delivered events."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> Response:
        if not url.endswith("/v1/enroll"):
            self.events.extend(posted_events(kwargs))
        return accept_all(url, **kwargs)
