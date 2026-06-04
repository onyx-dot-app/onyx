"""Mock upstream: echoes the request back so demos can assert what the
proxy forwarded (e.g. that the broker-injected Authorization arrived)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi import Request

app = FastAPI()


@app.api_route(
    "/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
)
async def echo(path: str, request: Request) -> dict[str, object]:
    body = await request.body()
    return {
        "method": request.method,
        "path": "/" + path,
        "query": dict(request.query_params),
        "headers": {k.lower(): v for k, v in request.headers.items()},
        "body_bytes": len(body),
        "body_preview": body[:512].decode("utf-8", errors="replace"),
    }
