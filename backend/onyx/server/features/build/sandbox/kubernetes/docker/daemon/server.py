import hashlib
import hmac
import os
import tarfile

import uvicorn
from fastapi import FastAPI
from fastapi import Header
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from push_daemon.extract import MAX_BUNDLE_BYTES
from push_daemon.extract import safe_extract_then_atomic_swap

app = FastAPI(title="sandbox-push-daemon", docs_url=None, redoc_url=None)

_PUSH_SECRET_ENV = "ONYX_SANDBOX_PUSH_SECRET"


def _check_authorization(authorization: str) -> None:
    secret = os.environ.get(_PUSH_SECRET_ENV, "")
    if not secret:
        raise HTTPException(status_code=500, detail="Push secret not configured")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    if not hmac.compare_digest(authorization[len("Bearer ") :], secret):
        raise HTTPException(status_code=401, detail="Invalid push secret")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/push")
async def push(
    request: Request,
    mount_path: str = Query(...),
    authorization: str = Header(...),
    x_bundle_sha256: str = Header(..., alias="X-Bundle-Sha256"),
) -> dict[str, str]:
    _check_authorization(authorization)

    if not mount_path.startswith("/"):
        raise HTTPException(status_code=400, detail="mount_path must be absolute")

    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > MAX_BUNDLE_BYTES:
        raise HTTPException(
            status_code=413, detail=f"Bundle exceeds {MAX_BUNDLE_BYTES} byte limit"
        )

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BUNDLE_BYTES:
            raise HTTPException(
                status_code=413, detail=f"Bundle exceeds {MAX_BUNDLE_BYTES} byte limit"
            )
        chunks.append(chunk)
    body = b"".join(chunks)

    actual_sha = hashlib.sha256(body).hexdigest()
    if actual_sha != x_bundle_sha256.lower():
        raise HTTPException(
            status_code=400,
            detail=f"SHA-256 mismatch: expected {x_bundle_sha256}, got {actual_sha}",
        )

    try:
        safe_extract_then_atomic_swap(body, mount_path)
    except (ValueError, tarfile.ReadError, tarfile.CompressionError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8731)
