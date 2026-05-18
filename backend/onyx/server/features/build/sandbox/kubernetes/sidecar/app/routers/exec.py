from __future__ import annotations

import asyncio
import base64
import logging
from contextlib import suppress

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import require_bearer_token
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/exec", tags=["exec"], dependencies=[Depends(require_bearer_token)]
)


class ExecRequest(BaseModel):
    argv: list[str] = Field(..., min_length=1, description="argv[0] is the executable.")
    cwd: str | None = None
    timeout_seconds: int | None = None
    stdin_b64: str | None = None


class ExecResponse(BaseModel):
    exit_code: int
    stdout_b64: str
    stderr_b64: str
    timed_out: bool
    stdout_truncated: bool = False
    stderr_truncated: bool = False


async def _read_capped(
    stream: asyncio.StreamReader | None,
    limit: int,
) -> tuple[bytes, bool]:
    """Read up to `limit` bytes from stream. Returns (data, truncated).

    If more data is available beyond the limit, drains the rest so the
    subprocess doesn't block writing to a full pipe.
    """
    if stream is None:
        return b"", False
    chunks: list[bytes] = []
    remaining = limit
    while remaining > 0:
        chunk = await stream.read(remaining)
        if not chunk:
            return b"".join(chunks), False
        chunks.append(chunk)
        remaining -= len(chunk)
    extra = await stream.read(1)
    if not extra:
        return b"".join(chunks), False
    # Truncated; drain the rest so the writer doesn't block on a full pipe.
    while True:
        chunk = await stream.read(64 * 1024)
        if not chunk:
            break
    return b"".join(chunks), True


@router.post("", response_model=ExecResponse)
async def run_exec(req: ExecRequest) -> ExecResponse:
    """Run an arbitrary command. Admin-gated: the bearer token represents control-plane trust.

    PR 2: minimal implementation suitable for break-glass and for the backend to
    bootstrap a session workspace. Output is base64-encoded so callers don't have
    to worry about binary or non-UTF-8 bytes.
    """
    settings = get_settings()
    timeout = req.timeout_seconds or settings.exec_default_timeout_seconds
    if timeout < 1 or timeout > settings.exec_max_timeout_seconds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"timeout_seconds must be in [1, {settings.exec_max_timeout_seconds}]"
            ),
        )

    stdin_bytes: bytes | None = None
    if req.stdin_b64 is not None:
        try:
            stdin_bytes = base64.b64decode(req.stdin_b64, validate=True)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"stdin_b64 is not valid base64: {exc}",
            ) from exc

    logger.info("Exec: argv=%r cwd=%r timeout=%ds", req.argv, req.cwd, timeout)
    try:
        proc = await asyncio.create_subprocess_exec(
            *req.argv,
            stdin=asyncio.subprocess.PIPE if stdin_bytes is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=req.cwd,
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
        # argv[0] missing / not executable, or cwd missing / not a directory.
        # Surface as 400 so callers see a useful error instead of an opaque 500.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot start subprocess: {exc}",
        ) from exc

    max_out = settings.max_exec_output_bytes
    timed_out = False
    stdout_trunc = False
    stderr_trunc = False
    stdout: bytes = b""
    stderr: bytes = b""

    async def _write_stdin() -> None:
        if stdin_bytes is not None and proc.stdin is not None:
            proc.stdin.write(stdin_bytes)
            # Subprocess can close its stdin before consuming all input —
            # normal for commands like `head -c 1` that read only part of
            # their stdin. drain() then gets EPIPE; treat as success.
            with suppress(BrokenPipeError, ConnectionResetError):
                await proc.stdin.drain()
            proc.stdin.close()

    async def _run() -> None:
        nonlocal stdout, stderr, stdout_trunc, stderr_trunc
        # Run stdin write concurrently with the stdout/stderr reads. Serializing
        # would deadlock when a subprocess interleaves stdin consumption with
        # output: the OS pipe + StreamReader buffers fill (~64 KB each way),
        # subprocess blocks writing, stops reading stdin, drain() never returns.
        # communicate() also buffers everything in memory — we replace it here
        # so a chatty subprocess can't blow up the sidecar's RSS.
        _, stdout_pair, stderr_pair = await asyncio.gather(
            _write_stdin(),
            _read_capped(proc.stdout, max_out),
            _read_capped(proc.stderr, max_out),
        )
        stdout, stdout_trunc = stdout_pair
        stderr, stderr_trunc = stderr_pair
        await proc.wait()

    try:
        await asyncio.wait_for(_run(), timeout=timeout)
    except TimeoutError:
        timed_out = True
        proc.kill()
        await proc.wait()

    return ExecResponse(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        stdout_b64=base64.b64encode(stdout).decode("ascii"),
        stderr_b64=base64.b64encode(stderr).decode("ascii"),
        timed_out=timed_out,
        stdout_truncated=stdout_trunc,
        stderr_truncated=stderr_trunc,
    )
