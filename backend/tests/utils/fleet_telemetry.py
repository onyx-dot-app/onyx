"""Sender builders and fake delivery transports for fleet telemetry tests."""

import gzip
import io
import json
from dataclasses import replace
from typing import Any

from onyx.utils.fleet_telemetry import BoundedTelemetry, TelemetryConfig

# An explicit identity, so senders deliver without enrollment.
TEST_CONFIG: TelemetryConfig = TelemetryConfig(
    endpoint="http://localhost:8787",
    token="test-token",
    customer_uuid="11111111-1111-4111-8111-111111111111",
    deployment_id="test-deployment",
    privacy_key=b"installation-secret-not-central-token",
)


def make_sender(*, capacity: int = 16, report_process: bool = True) -> BoundedTelemetry:
    """A sender with no delivery thread. Tests deliver with `flush_once`."""
    return BoundedTelemetry(
        replace(TEST_CONFIG, capacity=capacity), report_process=report_process
    )


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


def posted_events(request: dict[str, Any]) -> list[dict[str, Any]]:
    """The events in the gzip JSON body of one delivery request."""
    return json.loads(gzip.decompress(request["data"]))["events"]


def accept_all(*_args: Any, **kwargs: Any) -> Response:
    """A delivery transport that accepts every event of the request."""
    events: list[dict[str, Any]] = posted_events(kwargs)
    return Response(
        {"results": [{"index": i, "status": "accepted"} for i in range(len(events))]}
    )


class RecordingTransport:
    """Accepts every event, like `accept_all`, and keeps the delivered events."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Response:
        self.events.extend(posted_events(kwargs))
        return accept_all(*args, **kwargs)
