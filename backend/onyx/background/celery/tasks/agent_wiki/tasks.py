"""Push newly indexed public documents to Agent Wiki."""

from __future__ import annotations

import logging

import httpx
from celery import shared_task
from celery import Task

from onyx.configs.app_configs import AGENT_WIKI_API_KEY
from onyx.configs.app_configs import AGENT_WIKI_BASE_URL
from onyx.configs.app_configs import AGENT_WIKI_ENABLED
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 30
_MAX_RETRIES = 3


@shared_task(
    name=OnyxCeleryTask.PUSH_TO_AGENT_WIKI,
    queue=OnyxCeleryQueues.AGENT_WIKI_PUSH,
    bind=True,
    max_retries=_MAX_RETRIES,
    ignore_result=True,
)
def push_to_agent_wiki(
    self: Task,
    *,
    doc_id: str,
    source: str,
    title: str | None,
    content: str,
    url: str | None,
    doc_updated_at: str | None,
) -> None:
    if not AGENT_WIKI_ENABLED:
        return

    payload = {
        "content": content,
        "title": title,
        "source_type": source,
        "metadata": {"external_id": doc_id, "url": url},
        "updated_at": doc_updated_at,
    }

    try:
        with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
            response = client.post(
                f"{AGENT_WIKI_BASE_URL}/api/documents/ingest",
                json=payload,
                headers={"Authorization": f"Bearer {AGENT_WIKI_API_KEY}"},
            )
            response.raise_for_status()
        logger.debug("push_to_agent_wiki success doc_id=%s", doc_id)
    except httpx.HTTPStatusError as exc:
        if 400 <= exc.response.status_code < 500:
            logger.warning(
                "push_to_agent_wiki permanent error doc_id=%s status=%d, not retrying: %s",
                doc_id,
                exc.response.status_code,
                exc.response.text,
            )
            return
        countdown = 2 ** (self.request.retries + 4)
        logger.warning(
            "push_to_agent_wiki failed doc_id=%s status=%d attempt=%d, retrying in %ds",
            doc_id,
            exc.response.status_code,
            self.request.retries + 1,
            countdown,
        )
        self.retry(exc=exc, countdown=countdown)
    except Exception as exc:
        countdown = 2 ** (self.request.retries + 4)
        logger.warning(
            "push_to_agent_wiki failed doc_id=%s attempt=%d, retrying in %ds: %s",
            doc_id,
            self.request.retries + 1,
            countdown,
            exc,
        )
        self.retry(exc=exc, countdown=countdown)
