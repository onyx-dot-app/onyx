from __future__ import annotations

import asyncio
import base64
import stat
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import require_bearer_token
from app.config import get_settings

router = APIRouter(
    prefix="/files", tags=["files"], dependencies=[Depends(require_bearer_token)]
)


class WriteRequest(BaseModel):
    path: str = Field(..., description="Path relative to the workspace root.")
    content_b64: str = Field(..., description="Base64-encoded file content.")
    create_parents: bool = True


class WriteResponse(BaseModel):
    path: str
    size_bytes: int


class ReadResponse(BaseModel):
    path: str
    size_bytes: int
    content_b64: str


class ListEntry(BaseModel):
    name: str
    is_dir: bool
    size_bytes: int | None


class ListResponse(BaseModel):
    path: str
    entries: list[ListEntry]


def _resolve_within_workspace(rel: str) -> Path:
    """Resolve `rel` against the workspace root and reject anything that escapes it.

    Defense against path traversal: callers are trusted but we still anchor every
    path to the configured workspace root.
    """
    settings = get_settings()
    root = settings.workspace_root.resolve()
    candidate = (root / rel.lstrip("/")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path {rel!r} escapes workspace root",
        ) from exc
    return candidate


@router.get("/read", response_model=ReadResponse)
async def read_file(path: str) -> ReadResponse:
    target = _resolve_within_workspace(path)
    if not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {path}",
        )

    limit = get_settings().max_read_bytes
    # Bounded read: cap memory at limit+1 bytes so a concurrent grow on the
    # underlying file from the sandbox container (which is untrusted from the
    # sidecar's perspective) can't bypass the size cap via TOCTOU. Wrapped in
    # asyncio.to_thread so a 100MiB read doesn't block the event loop.
    data = await asyncio.to_thread(_read_bounded, target, limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds max_read_bytes {limit}",
        )

    return ReadResponse(
        path=path,
        size_bytes=len(data),
        content_b64=base64.b64encode(data).decode("ascii"),
    )


def _read_bounded(path: Path, max_bytes: int) -> bytes:
    with path.open("rb") as fh:
        return fh.read(max_bytes)


@router.post("/write", response_model=WriteResponse)
async def write_file(req: WriteRequest) -> WriteResponse:
    try:
        data = base64.b64decode(req.content_b64, validate=True)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"content_b64 is not valid base64: {exc}",
        ) from exc

    settings = get_settings()
    if len(data) > settings.max_write_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Payload size {len(data)} exceeds max_write_bytes {settings.max_write_bytes}",
        )

    target = _resolve_within_workspace(req.path)
    if not req.create_parents and not target.parent.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Parent directory does not exist: {target.parent}",
        )

    # Defer the blocking write to a thread so the event loop stays responsive.
    await asyncio.to_thread(_write_file, target, data, req.create_parents)
    return WriteResponse(path=req.path, size_bytes=len(data))


def _write_file(path: Path, data: bytes, create_parents: bool) -> None:
    if create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@router.get("/list", response_model=ListResponse)
async def list_dir(path: str) -> ListResponse:
    target = _resolve_within_workspace(path)
    if not target.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Directory not found: {path}",
        )

    entries = await asyncio.to_thread(_scan_directory, target)
    return ListResponse(path=path, entries=entries)


def _scan_directory(path: Path) -> list[ListEntry]:
    entries: list[ListEntry] = []
    for entry in sorted(path.iterdir(), key=lambda p: p.name):
        # lstat() so a broken symlink doesn't raise FileNotFoundError. The
        # sandbox container runs user code that can create broken symlinks;
        # surfacing those as 500s is wrong. lstat-style metadata also matches
        # the behaviour of `ls -l`.
        st = entry.lstat()
        is_dir = stat.S_ISDIR(st.st_mode)
        size_bytes = None if is_dir else st.st_size
        entries.append(ListEntry(name=entry.name, is_dir=is_dir, size_bytes=size_bytes))
    return entries
