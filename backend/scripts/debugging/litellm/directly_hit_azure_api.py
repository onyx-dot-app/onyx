#!/usr/bin/env python3
"""
Directly hit Azure OpenAI endpoints for debugging.

This script bypasses LiteLLM and directly calls Azure OpenAI APIs.
Uses URL and API key constants plus a payload.json in the same directory.

Usage:
    python directly_hit_azure_api.py
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx


# Configuration: Update these values before running
URL = "https://YOUR_AZURE_OPENAI_DEPLOYMENT_URL_HERE.cognitiveservices.azure.com/"
API_KEY = "YOUR_API_KEY_HERE"

PAYLOAD_PATH = Path(__file__).resolve().with_name("payload.json")


def _load_payload_json() -> dict:
    """Load and parse payload.json file."""
    if not PAYLOAD_PATH.exists():
        raise FileNotFoundError(
            f"payload.json not found at {PAYLOAD_PATH!r}. "
            "Create payload.json next to this script."
        )
    return json.loads(PAYLOAD_PATH.read_text())


def _print_response(resp: httpx.Response) -> None:
    """Print HTTP response in a readable format."""
    print(f"HTTP {resp.status_code}")

    content_type = resp.headers.get("content-type", "")
    raw = resp.content
    if not raw:
        return

    if "json" in content_type.lower():
        try:
            obj = resp.json()
            print(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False))
            return
        except Exception:
            pass

    # Fallback: print as text (replace errors to avoid crashes).
    print(raw.decode("utf-8", errors="replace"))


def main() -> int:
    """Main entry point."""
    if (
        URL
        == "https://YOUR_AZURE_OPENAI_DEPLOYMENT_URL_HERE.cognitiveservices.azure.com/"
    ):
        raise SystemExit(
            "Please set the URL constant at the top of this file to your Azure OpenAI deployment URL."
        )
    if API_KEY == "YOUR_API_KEY_HERE":
        raise SystemExit(
            "Please set the API_KEY constant at the top of this file to your Azure OpenAI API key."
        )

    payload = _load_payload_json()

    headers = {
        "api-key": API_KEY,
        "content-type": "application/json",
    }

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            url=URL,
            headers=headers,
            json=payload,
        )

    _print_response(resp)
    return 0 if resp.is_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
