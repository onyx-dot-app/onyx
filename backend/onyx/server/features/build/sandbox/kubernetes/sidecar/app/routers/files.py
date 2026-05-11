from __future__ import annotations

import base64
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

    settings = get_settings()
    size = target.stat().st_size
    if size > settings.max_read_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size {size} exceeds max_read_bytes {settings.max_read_bytes}",
        )

    data = target.read_bytes()
    return ReadResponse(
        path=path,
        size_bytes=size,
        content_b64=base64.b64encode(data).decode("ascii"),
    )


@router.post("/write")
async def write_file(req: WriteRequest) -> dict[str, str | int]:
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
    if req.create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
    elif not target.parent.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Parent directory does not exist: {target.parent}",
        )

    target.write_bytes(data)
    return {"path": req.path, "size_bytes": len(data)}


@router.get("/list", response_model=ListResponse)
async def list_dir(path: str) -> ListResponse:
    target = _resolve_within_workspace(path)
    if not target.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Directory not found: {path}",
        )

    entries: list[ListEntry] = []
    for entry in sorted(target.iterdir(), key=lambda p: p.name):
        is_dir = entry.is_dir()
        entries.append(
            ListEntry(
                name=entry.name,
                is_dir=is_dir,
                size_bytes=None if is_dir else entry.stat().st_size,
            )
        )
    return ListResponse(path=path, entries=entries)
