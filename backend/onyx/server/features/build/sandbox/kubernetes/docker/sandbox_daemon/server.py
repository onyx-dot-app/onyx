import asyncio
import base64
import binascii
import hashlib
import os
import tarfile
import time

import uvicorn
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import FastAPI
from fastapi import Header
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from sandbox_daemon.extract import MAX_BUNDLE_BYTES
from sandbox_daemon.extract import safe_extract_then_atomic_swap
from sandbox_daemon.models import SnapshotCreateRequest
from sandbox_daemon.models import SnapshotCreateResponse
from sandbox_daemon.models import SnapshotRestoreRequest
from sandbox_daemon.snapshot import create_snapshot
from sandbox_daemon.snapshot import restore_snapshot
from sandbox_daemon.snapshot import SnapshotError

app = FastAPI(title="sandbox-sidecar", docs_url=None, redoc_url=None)

_PUSH_PUBLIC_KEY_ENV = "ONYX_SANDBOX_PUSH_PUBLIC_KEY"
_MAX_TIMESTAMP_DRIFT_SECONDS = 60

_public_key: Ed25519PublicKey | None = None


def _get_public_key() -> Ed25519PublicKey:
    global _public_key
    if _public_key is not None:
        return _public_key

    raw_b64 = os.environ.get(_PUSH_PUBLIC_KEY_ENV, "")
    if not raw_b64:
        raise HTTPException(status_code=500, detail="Push public key not configured")
    try:
        pub_bytes = base64.b64decode(raw_b64)
        _public_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"Push public key is not a valid base64-encoded Ed25519 key: {e}",
        )
    return _public_key


def _verify_signature(
    path: str,
    sha256_hex: str,
    signature_b64: str,
    timestamp: str,
) -> None:
    """Verify timestamp drift and Ed25519 signature over {timestamp}|{path}|{sha256_hex}."""
    try:
        ts_int = int(timestamp)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid timestamp")
    if abs(time.time() - ts_int) > _MAX_TIMESTAMP_DRIFT_SECONDS:
        raise HTTPException(status_code=401, detail="Timestamp out of range")

    try:
        sig = base64.b64decode(signature_b64)
    except binascii.Error:
        raise HTTPException(status_code=401, detail="Invalid signature encoding")

    message = f"{timestamp}|{path}|{sha256_hex}".encode()
    try:
        _get_public_key().verify(sig, message)
    except InvalidSignature:
        raise HTTPException(status_code=401, detail="Invalid signature")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/push")
async def push(
    request: Request,
    mount_path: str = Query(...),
    x_bundle_sha256: str = Header(..., alias="X-Bundle-Sha256"),
    x_push_signature: str = Header(..., alias="X-Push-Signature"),
    x_push_timestamp: str = Header(..., alias="X-Push-Timestamp"),
) -> dict[str, str]:
    _verify_signature(
        mount_path, x_bundle_sha256.lower(), x_push_signature, x_push_timestamp
    )

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


@app.post("/snapshot/create")
async def snapshot_create(
    request: Request,
    x_push_signature: str = Header(..., alias="X-Push-Signature"),
    x_push_timestamp: str = Header(..., alias="X-Push-Timestamp"),
) -> SnapshotCreateResponse:
    body = await request.body()
    _verify_signature(
        "/snapshot/create",
        hashlib.sha256(body).hexdigest(),
        x_push_signature,
        x_push_timestamp,
    )

    try:
        payload = SnapshotCreateRequest.model_validate_json(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid request body: {e}")

    try:
        status, storage_path = await asyncio.to_thread(
            create_snapshot,
            session_id=payload.session_id,
            tenant_id=payload.tenant_id,
            s3_bucket=payload.s3_bucket,
            snapshot_id=payload.snapshot_id,
        )
    except SnapshotError as e:
        raise HTTPException(status_code=500, detail=f"Snapshot create failed: {e}")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Snapshot create OS error: {e}")

    return SnapshotCreateResponse(
        status=status, storage_path=storage_path, size_bytes=0
    )


@app.post("/snapshot/restore", status_code=204)
async def snapshot_restore(
    request: Request,
    x_push_signature: str = Header(..., alias="X-Push-Signature"),
    x_push_timestamp: str = Header(..., alias="X-Push-Timestamp"),
) -> None:
    body = await request.body()
    _verify_signature(
        "/snapshot/restore",
        hashlib.sha256(body).hexdigest(),
        x_push_signature,
        x_push_timestamp,
    )

    try:
        payload = SnapshotRestoreRequest.model_validate_json(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid request body: {e}")

    try:
        await asyncio.to_thread(
            restore_snapshot,
            session_id=payload.session_id,
            s3_bucket=payload.s3_bucket,
            storage_path=payload.storage_path,
        )
    except SnapshotError as e:
        raise HTTPException(status_code=500, detail=f"Snapshot restore failed: {e}")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Snapshot restore OS error: {e}")


if __name__ == "__main__":
    # TODO(security): bind to 127.0.0.1 and front with an in-pod proxy, or
    # restrict the listener to the sandbox network namespace.
    uvicorn.run(app, host="0.0.0.0", port=8731)  # noqa: S104
