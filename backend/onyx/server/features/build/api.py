from collections.abc import Iterator

import httpx
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from fastapi.responses import StreamingResponse

from onyx.auth.users import current_user
from onyx.configs.app_configs import BUILD_WEBAPP_URL
from onyx.db.models import User
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/build")

# Separate router for Next.js static assets at /_next/*
# This is needed because Next.js apps reference assets with root-relative paths
nextjs_assets_router = APIRouter()

# Headers to skip when proxying (hop-by-hop headers)
EXCLUDED_HEADERS = {
    "content-encoding",
    "content-length",
    "transfer-encoding",
    "connection",
}

# Base path where the webapp is served
WEBAPP_BASE_PATH = "/api/build/webapp"


def _stream_response(response: httpx.Response) -> Iterator[bytes]:
    """Stream the response content in chunks."""
    for chunk in response.iter_bytes(chunk_size=8192):
        yield chunk


def _rewrite_asset_paths(content: bytes) -> bytes:
    """Rewrite Next.js asset paths to go through the proxy."""
    text = content.decode("utf-8")
    # Rewrite /_next/ paths to go through our proxy
    text = text.replace("/_next/", f"{WEBAPP_BASE_PATH}/_next/")
    # Rewrite data.json fetch paths
    text = text.replace('"/data.json"', f'"{WEBAPP_BASE_PATH}/data.json"')
    text = text.replace("'/data.json'", f"'{WEBAPP_BASE_PATH}/data.json'")
    text = text.replace('"/favicon.ico', f'"{WEBAPP_BASE_PATH}/favicon.ico')
    return text.encode("utf-8")


# Content types that may contain asset path references that need rewriting
REWRITABLE_CONTENT_TYPES = {
    "text/html",
    "text/css",
    "application/javascript",
    "text/javascript",
    "application/x-javascript",
}


def _proxy_request(path: str, request: Request) -> StreamingResponse | Response:
    """Proxy a request to the configured BUILD_WEBAPP_URL."""
    if not BUILD_WEBAPP_URL:
        raise HTTPException(
            status_code=503,
            detail="BUILD_WEBAPP_URL is not configured",
        )

    # Build the target URL
    target_url = f"{BUILD_WEBAPP_URL.rstrip('/')}/{path.lstrip('/')}"

    # Include query params if present
    if request.query_params:
        target_url = f"{target_url}?{request.query_params}"

    logger.debug(f"Proxying request to: {target_url}")

    try:
        # Make the request to the target URL
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.get(
                target_url,
                headers={
                    key: value
                    for key, value in request.headers.items()
                    if key.lower() not in ("host", "content-length")
                },
            )

            # Build response headers, excluding hop-by-hop headers
            response_headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower() not in EXCLUDED_HEADERS
            }

            content_type = response.headers.get("content-type", "")

            # For HTML/CSS/JS responses, rewrite asset paths
            if any(ct in content_type for ct in REWRITABLE_CONTENT_TYPES):
                content = _rewrite_asset_paths(response.content)
                return Response(
                    content=content,
                    status_code=response.status_code,
                    headers=response_headers,
                    media_type=content_type,
                )

            return StreamingResponse(
                content=_stream_response(response),
                status_code=response.status_code,
                headers=response_headers,
                media_type=content_type or None,
            )

    except httpx.TimeoutException:
        logger.error(f"Timeout while proxying request to {target_url}")
        raise HTTPException(status_code=504, detail="Gateway timeout")
    except httpx.RequestError as e:
        logger.error(f"Error proxying request to {target_url}: {e}")
        raise HTTPException(status_code=502, detail="Bad gateway")


@router.get("/webapp", response_model=None)
def get_webapp_root(
    request: Request, _: User = Depends(current_user)
) -> StreamingResponse | Response:
    """Proxy the root path of the webapp."""
    return _proxy_request("", request)


@router.get("/webapp/{path:path}", response_model=None)
def get_webapp_path(
    path: str, request: Request, _: User = Depends(current_user)
) -> StreamingResponse | Response:
    """Proxy any subpath of the webapp (static assets, etc.)."""
    return _proxy_request(path, request)


@nextjs_assets_router.get("/_next/{path:path}", response_model=None)
def get_nextjs_assets(
    path: str, request: Request, _: User = Depends(current_user)
) -> StreamingResponse | Response:
    """Proxy Next.js static assets requested at root /_next/ path."""
    return _proxy_request(f"_next/{path}", request)
