from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.auth import require_bearer_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/snapshot",
    tags=["snapshot"],
    dependencies=[Depends(require_bearer_token)],
)


@router.post("")
async def trigger_snapshot() -> dict[str, str]:
    """Trigger an on-demand snapshot.

    PR 2: stub. Logs the call and returns. Real S3 / VolumeSnapshot logic lands in PR 5,
    which will wire this endpoint to an actual snapshot runner.
    """
    logger.info("Snapshot endpoint invoked (PR 2 stub — real implementation in PR 5)")
    return {"status": "accepted", "detail": "snapshot stub — not yet implemented"}
