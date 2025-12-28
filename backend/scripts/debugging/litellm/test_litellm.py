#!/usr/bin/env python3
"""
Test LiteLLM integration and output raw stream events.

This script uses Onyx's LiteLLM instance (with monkey patches) to make a completion
request and outputs the raw stream events as JSON, one per line.

Usage:
    # Set environment variables if needed:
    export LITELLM_DEBUG=1  # Optional: enable LiteLLM debug logs

    # Update the configuration below, then run:
    python test_litellm.py
"""

import json
import os
from typing import Any

from onyx.llm.litellm_singleton import litellm

# Optional: enable LiteLLM debug logs (set `LITELLM_DEBUG=1`)
if os.getenv("LITELLM_DEBUG") == "1":
    getattr(litellm, "_turn_on_debug", lambda: None)()

# Configuration: Update these values before running
MODEL = "azure/responses/YOUR_MODEL_NAME_HERE"
API_KEY = "YOUR_API_KEY_HERE"
BASE_URL = "https://YOUR_DEPLOYMENT_URL_HERE.cognitiveservices.azure.com"
API_VERSION = "2025-03-01-preview"  # For Azure, must be 2025-03-01-preview

# Example messages - customize as needed
MESSAGES = [
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "Hello! How can I help you today?"},
    {"role": "user", "content": "what is onyx? search internally and the web"},
]

stream = litellm.completion(
    mock_response=None,
    # Insert /responses/ between provider and model to use the litellm completions ->responses bridge
    model=MODEL,
    api_key=API_KEY,
    base_url=BASE_URL,
    api_version=API_VERSION,
    custom_llm_provider=None,
    messages=MESSAGES,
    tools=[
        {
            "type": "function",
            "function": {
                "name": "internal_search",
                "description": "Search connected applications for information.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "queries": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of search queries to execute, typically a single query.",
                        }
                    },
                    "required": ["queries"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "generate_image",
                "description": "Generate an image based on a prompt. Do not use unless the user specifically requests an image.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "Prompt used to generate the image",
                        },
                        "shape": {
                            "type": "string",
                            "description": "Optional - only specify if you want a specific shape. "
                            "Image shape: 'square', 'portrait', or 'landscape'.",
                            "enum": ["square", "portrait", "landscape"],
                        },
                    },
                    "required": ["prompt"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for information. "
                "Returns a list of search results with titles, metadata, and snippets.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "queries": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "One or more queries to look up on the web.",
                        }
                    },
                    "required": ["queries"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "open_url",
                "description": "Open and read the content of one or more URLs. Returns the text content of the pages.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of URLs to open and read. Can be a single URL or multiple URLs.",
                        }
                    },
                    "required": ["urls"],
                },
            },
        },
    ],
    tool_choice="auto",
    stream=True,
    temperature=1,
    timeout=600,
    max_tokens=None,
    stream_options={"include_usage": True},
    reasoning={"effort": "low", "summary": "auto"},
    parallel_tool_calls=True,
    allowed_openai_params=["tool_choice"],
)


def _to_jsonable(x: Any) -> Any:
    """Convert an object to a JSON-serializable format.

    Handles Pydantic models, dataclasses, and other common types.
    """
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    if isinstance(x, dict):
        return {k: _to_jsonable(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_to_jsonable(v) for v in x]
    if hasattr(x, "model_dump"):
        return _to_jsonable(x.model_dump())
    if hasattr(x, "dict"):
        try:
            return _to_jsonable(x.dict())
        except Exception:
            pass
    return str(x)


if __name__ == "__main__":
    # Output raw stream events as JSON, one per line
    for event in stream:
        print(json.dumps(_to_jsonable(event), ensure_ascii=False), flush=True)
