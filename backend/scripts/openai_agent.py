"""Shared OpenAI Responses API client for repo agent-task scripts.

Standard-library-only on purpose: GitHub Actions runners invoke these scripts
with bare python3 (no uv, no deps). Each task script only writes its prompt,
output schema, and validation; this module owns the API plumbing.

`call_responses_api` submits in background mode and polls — research calls
with web_search routinely exceed what a synchronous request tolerates. It
returns the completed response object; `extract_output_text` turns it into
the JSON text the caller parses and validates.

Usage:
    from openai_agent import WEB_SEARCH_TOOL, call_responses_api, extract_output_text
"""

import json
import time
import urllib.request
from typing import Any

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
# Built-in web search tool on the Responses API.
WEB_SEARCH_TOOL = {"type": "web_search"}


def api_request(
    path: str, api_key: str, timeout: float, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    request: urllib.request.Request = urllib.request.Request(  # noqa: S310
        f"{OPENAI_RESPONSES_URL}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read())


def call_responses_api(
    prompt: str,
    model: str,
    api_key: str,
    schema: dict[str, Any],
    timeout: float,
    reasoning_effort: str = "medium",
    response_id: str | None = None,
    poll_interval: float = 15.0,
) -> dict[str, Any]:
    """Submit in background mode and poll until the response settles.

    `schema` is a strict-mode JSON schema for structured output. Pass
    `response_id` to resume polling an existing background response."""
    if response_id is None:
        body = {
            "model": model,
            "background": True,
            "reasoning": {"effort": reasoning_effort},
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                }
            ],
            "tools": [WEB_SEARCH_TOOL],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "task_output",
                    "schema": schema,
                    "strict": True,
                }
            },
        }
        submitted: dict[str, Any] = api_request("", api_key, 60.0, body)
        response_id = submitted.get("id")
        if not response_id:
            raise ValueError(f"No response id in submission: {submitted}")
    else:
        submitted = {}

    deadline: float = time.monotonic() + timeout
    while True:
        status: str | None = submitted.get("status")
        if status in ("completed", "failed", "cancelled", "incomplete"):
            return submitted
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Response {response_id} still {status} after {timeout}s"
            )
        time.sleep(poll_interval)
        submitted = api_request(f"/{response_id}", api_key, 60.0)
        status = submitted.get("status")
        print(f"  response {response_id}: {status}", flush=True)


def extract_output_text(response: dict[str, Any]) -> str:
    if response.get("status") == "incomplete":
        details = response.get("incomplete_details") or {}
        raise ValueError(f"Response incomplete: {details.get('reason', 'unknown')}")
    if response.get("status") not in (None, "completed"):
        raise ValueError(
            f"Response status {response.get('status')!r}: "
            f"{json.dumps(response.get('error'))[:500]}"
        )
    texts: list[str] = []
    for item in response.get("output") or []:
        if item.get("type") != "message":
            continue
        texts.extend(
            content.get("text") or ""
            for content in item.get("content") or []
            if content.get("type") == "output_text"
        )
    text = "".join(texts).strip()
    if not text:
        raise ValueError("No output_text in response")
    return text
