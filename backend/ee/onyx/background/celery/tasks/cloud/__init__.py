"""Celery cloud tasks."""

from ee.onyx.background.celery.tasks.cloud.tasks import (  # noqa: F401
    cloud_beat_task_generator,
)

__all__ = ["cloud_beat_task_generator"]
