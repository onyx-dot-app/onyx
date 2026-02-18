"""Shared celery tasks."""

from onyx.background.celery.tasks.shared.tasks import (
    celery_beat_heartbeat,
)  # noqa: F401
from onyx.background.celery.tasks.shared.tasks import (  # noqa: F401
    document_by_cc_pair_cleanup_task,
)

__all__ = ["celery_beat_heartbeat", "document_by_cc_pair_cleanup_task"]
