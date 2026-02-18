"""Celery tasks for document fetching."""

from onyx.background.celery.tasks.docfetching.tasks import (  # noqa: F401
    docfetching_proxy_task,
)

__all__ = ["docfetching_proxy_task"]
