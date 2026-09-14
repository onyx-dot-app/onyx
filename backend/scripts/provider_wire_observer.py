"""Opt-in HTTP-boundary observation; never stores prompts, headers, or keys."""

import json
import threading
import time


def install_wire_observer(output, write_json):
    import httpx

    original = httpx.Client.send
    lock = threading.Lock()
    sequence = 0

    def send(client, request, *args, **kwargs):
        nonlocal sequence
        if request.url.path != "/v1/responses":
            return original(client, request, *args, **kwargs)
        body = json.loads(request.content)
        if body.get("model") not in {"gpt-5.6-luna", "gpt-5.6-sol"}:
            return original(client, request, *args, **kwargs)
        with lock:
            sequence += 1
            call_id = sequence
        record = {
            "model": body["model"],
            "reasoning": body.get("reasoning"),
            "max_output_tokens": body.get("max_output_tokens"),
            "path": request.url.path,
        }
        path = output / f"provider-wire-{call_id:04d}.json"
        write_json(path, record)
        started = time.monotonic()
        response = original(client, request, *args, **kwargs)
        record["http_status"] = response.status_code
        record["headers_ms"] = (time.monotonic() - started) * 1000
        if kwargs.get("stream", False):
            inner = response.stream

            class ObservedStream(httpx.SyncByteStream):
                def __iter__(self):
                    pending = b""
                    try:
                        for chunk in inner:  # ty: ignore[not-iterable] Sync Client responses always use SyncByteStream.
                            pending += chunk
                            while b"\n" in pending:
                                line, pending = pending.split(b"\n", 1)
                                if not line.startswith(b"data: "):
                                    continue
                                try:
                                    event = json.loads(line[6:])
                                except (ValueError, UnicodeDecodeError):
                                    continue
                                kind = event.get("type", "")
                                if kind in (
                                    "response.output_text.delta",
                                    "response.function_call_arguments.delta",
                                ):
                                    record.setdefault(
                                        "first_output_ms",
                                        (time.monotonic() - started) * 1000,
                                    )
                                if kind in (
                                    "response.completed",
                                    "response.incomplete",
                                    "response.failed",
                                ):
                                    record["usage"] = event.get("response", {}).get(
                                        "usage"
                                    )
                                    record["response_status"] = event.get(
                                        "response", {}
                                    ).get("status")
                                    record["incomplete_details"] = event.get(
                                        "response", {}
                                    ).get("incomplete_details")
                            yield chunk
                    finally:
                        record["elapsed_ms"] = (time.monotonic() - started) * 1000
                        write_json(path, record)

                def close(self):
                    inner.close()  # ty: ignore[unresolved-attribute] Sync Client responses always use SyncByteStream.

            response.stream = ObservedStream()
        if not kwargs.get("stream", False):
            data = response.json()
            record["response_model"] = data.get("model")
            record["usage"] = data.get("usage")
        write_json(path, record)
        return response

    httpx.Client.send = send
