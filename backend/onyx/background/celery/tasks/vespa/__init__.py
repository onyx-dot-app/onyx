"""Celery tasks for Vespa sync."""

from onyx.background.celery.tasks.vespa.tasks import (
    check_for_vespa_sync_task,
)  # noqa: F401
from onyx.background.celery.tasks.vespa.tasks import (
    vespa_metadata_sync_task,
)  # noqa: F401

__all__ = ["check_for_vespa_sync_task", "vespa_metadata_sync_task"]
