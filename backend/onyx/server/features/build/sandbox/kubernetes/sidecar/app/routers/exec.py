from __future__ import annotations

import asyncio
import base64
import logging

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
    proc = await asyncio.create_subprocess_exec(
        *req.argv,
        stdin=asyncio.subprocess.PIPE if stdin_bytes is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=req.cwd,
    )

    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin_bytes),
            timeout=timeout,
        )
    except TimeoutError:
        timed_out = True
        proc.kill()
        stdout, stderr = await proc.communicate()

    return ExecResponse(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        stdout_b64=base64.b64encode(stdout or b"").decode("ascii"),
        stderr_b64=base64.b64encode(stderr or b"").decode("ascii"),
        timed_out=timed_out,
    )
