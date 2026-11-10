"""Repository webhooks are not connector events."""

from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from onyx.background.celery.tasks.marketplace_sync.tasks import (
    dispatch_marketplace_sync,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.marketplace_webhook import receive_marketplace_webhook__no_commit
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger
from onyx.webhook_server.routes import read_webhook_body
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter()
logger = setup_logger()


class MarketplaceWebhookResponse(BaseModel):
    queued: bool


@router.post("/marketplaces/{marketplace_id}/github", include_in_schema=False)
async def receive_marketplace_webhook(
    marketplace_id: UUID, request: Request
) -> MarketplaceWebhookResponse:
    if MULTI_TENANT:
        raise OnyxError(OnyxErrorCode.NOT_FOUND)
    body = await read_webhook_body(request)
    return await run_in_threadpool(
        _receive,
        marketplace_id,
        body,
        request.headers.get("x-hub-signature-256", ""),
        request.headers.get("x-github-event", ""),
        request.headers.get("x-github-hook-id", ""),
    )


def _receive(
    marketplace_id: UUID, body: bytes, signature: str, event: str, hook_id: str
) -> MarketplaceWebhookResponse:
    with get_session_with_current_tenant() as session:
        queued = receive_marketplace_webhook__no_commit(
            marketplace_id,
            body,
            signature=signature,
            event=event,
            hook_id=hook_id,
            db_session=session,
        )
        session.commit()
    if queued:
        try:
            dispatch_marketplace_sync(get_current_tenant_id(), marketplace_id)
        except Exception:
            logger.warning("Marketplace webhook dispatch deferred: %s", marketplace_id)
    return MarketplaceWebhookResponse(queued=queued)
