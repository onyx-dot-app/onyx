"""Push newly indexed public documents to Agent Wiki."""

from __future__ import annotations

import logging
import time

import httpx

from onyx.configs.app_configs import AGENT_WIKI_API_KEY
from onyx.configs.app_configs import AGENT_WIKI_BASE_URL

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 30
_MAX_RETRIES = 3


def push_to_agent_wiki(
    *,
    doc_id: str,
    source: str,
    title: str | None,
    content: str,
    url: str | None,
    doc_updated_at: str | None,
) -> None:
    """HTTP push with exponential backoff retry. Runs in a background thread."""
    payload = {
        "content": content,
        "title": title,
        "source_type": source,
        "metadata": {"external_id": doc_id, "url": url},
        "updated_at": doc_updated_at,
    }

    for attempt in range(_MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
                response = client.post(
                    f"{AGENT_WIKI_BASE_URL}/api/documents/ingest",
                    json=payload,
                    headers={"Authorization": f"Bearer {AGENT_WIKI_API_KEY}"},
                )
                response.raise_for_status()
            logger.debug("push_to_agent_wiki success doc_id=%s", doc_id)
            return
        except httpx.HTTPStatusError as exc:
            if 400 <= exc.response.status_code < 500:
                logger.warning(
                    "push_to_agent_wiki permanent error doc_id=%s status=%d, not retrying: %s",
                    doc_id,
                    exc.response.status_code,
                    exc.response.text,
                )
                return
            if attempt == _MAX_RETRIES:
                logger.warning(
                    "push_to_agent_wiki failed doc_id=%s status=%d after %d attempts",
                    doc_id,
                    exc.response.status_code,
                    _MAX_RETRIES + 1,
                )
                return
        except Exception as exc:
            if attempt == _MAX_RETRIES:
                logger.warning(
                    "push_to_agent_wiki failed doc_id=%s after %d attempts: %s",
                    doc_id,
                    _MAX_RETRIES + 1,
                    exc,
                )
                return

        sleep_secs = 2 ** (attempt + 4)
        logger.debug(
            "push_to_agent_wiki retrying doc_id=%s attempt=%d in %ds",
            doc_id,
            attempt + 1,
            sleep_secs,
        )
        time.sleep(sleep_secs)
