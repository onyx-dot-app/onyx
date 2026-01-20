#!/usr/bin/env python3
"""
AgentGateway Proxy Server

This proxy bridges the gap between LiteLLM's OpenAI-compatible API calls
and AgentGateway's endpoint structure. It handles:
1. URL path translation (/chat/completions -> /gemini)
2. Streaming response conversion (JSON -> SSE format)
3. Response format normalization (usage tokens, model names)

Configuration via environment variables:
- AGENTGATEWAY_URL: Target AgentGateway endpoint (required)
- PROXY_PORT: Port to run the proxy on (default: 8888)
- LOG_LEVEL: Logging level (default: INFO)
"""

import os
import json
import time
import logging
from flask import Flask, request, Response
import requests

# Configuration from environment variables
AGENTGATEWAY_URL = os.environ.get("AGENTGATEWAY_URL")
PROXY_PORT = int(os.environ.get("PROXY_PORT", "8888"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Setup logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def generate_sse_response(content: str, model: str, completion_id: str):
    """Convert a non-streaming response to SSE (Server-Sent Events) format."""
    # First chunk with the content
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {
                "role": "assistant",
                "content": content
            },
            "finish_reason": None
        }]
    }
    yield f"data: {json.dumps(chunk)}\n\n"

    # Final chunk with finish_reason
    final_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop"
        }]
    }
    yield f"data: {json.dumps(final_chunk)}\n\n"
    yield "data: [DONE]\n\n"


@app.route("/v1/chat/completions", methods=["POST"])
@app.route("/chat/completions", methods=["POST"])
def proxy():
    """Proxy endpoint that forwards requests to AgentGateway."""
    if not AGENTGATEWAY_URL:
        logger.error("AGENTGATEWAY_URL environment variable not set")
        return Response(
            json.dumps({"error": "AGENTGATEWAY_URL not configured"}),
            status=500,
            content_type="application/json"
        )

    req_json = request.json
    requested_model = req_json.get("model", "gemini-2.5-flash")
    is_streaming = req_json.get("stream", False)

    logger.info(f"Received request - model: {requested_model}, stream: {is_streaming}")
    logger.debug(f"Full request body: {json.dumps(req_json)}")

    try:
        # Always send non-streaming request to AgentGateway
        forward_req = req_json.copy()
        forward_req["stream"] = False

        resp = requests.post(
            AGENTGATEWAY_URL,
            json=forward_req,
            headers={"Content-Type": "application/json"},
            timeout=120
        )
        logger.info(f"AgentGateway response status: {resp.status_code}")

        if resp.status_code != 200:
            logger.error(f"AgentGateway error: {resp.text}")
            return Response(resp.text, status=resp.status_code, content_type="application/json")

        resp_json = resp.json()
        logger.debug(f"AgentGateway response: {json.dumps(resp_json)}")

        # Extract the content from the response
        content = ""
        if "choices" in resp_json and len(resp_json["choices"]) > 0:
            message = resp_json["choices"][0].get("message", {})
            content = message.get("content", "")

        completion_id = resp_json.get("id", f"chatcmpl-{int(time.time())}")

        if is_streaming:
            # Return SSE streaming response
            logger.info(f"Returning streaming response with content length: {len(content)}")
            return Response(
                generate_sse_response(content, requested_model, completion_id),
                status=200,
                content_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )
        else:
            # Return non-streaming response with normalized format
            resp_json["model"] = requested_model

            # Fix usage format to match OpenAI spec
            if "usage" in resp_json:
                old_usage = resp_json["usage"]
                resp_json["usage"] = {
                    "prompt_tokens": old_usage.get("promptTokenCount", old_usage.get("prompt_tokens", 0)),
                    "completion_tokens": old_usage.get("candidatesTokenCount", old_usage.get("completion_tokens", 0)),
                    "total_tokens": old_usage.get("totalTokenCount", old_usage.get("total_tokens", 0))
                }

            if "object" not in resp_json:
                resp_json["object"] = "chat.completion"
            if "created" not in resp_json:
                resp_json["created"] = int(time.time())

            logger.debug(f"Returning response: {json.dumps(resp_json)}")
            return Response(json.dumps(resp_json), status=200, content_type="application/json")

    except requests.exceptions.Timeout:
        logger.error("Request to AgentGateway timed out")
        return Response(
            json.dumps({"error": "Request timed out"}),
            status=504,
            content_type="application/json"
        )
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error to AgentGateway: {e}")
        return Response(
            json.dumps({"error": f"Cannot connect to AgentGateway: {str(e)}"}),
            status=502,
            content_type="application/json"
        )
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return Response(
            json.dumps({"error": str(e)}),
            status=500,
            content_type="application/json"
        )


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return {"status": "ok", "agentgateway_url": AGENTGATEWAY_URL or "NOT SET"}


if __name__ == "__main__":
    if not AGENTGATEWAY_URL:
        logger.warning("AGENTGATEWAY_URL not set - proxy will return errors until configured")
    else:
        logger.info(f"AgentGateway URL: {AGENTGATEWAY_URL}")

    logger.info(f"Starting AgentGateway proxy on port {PROXY_PORT}")
    app.run(host="0.0.0.0", port=PROXY_PORT)
