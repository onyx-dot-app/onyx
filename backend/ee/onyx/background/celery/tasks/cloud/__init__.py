"""Celery cloud tasks."""

from ee.onyx.background.celery.tasks.cloud.tasks import (
    cloud_beat_task_generator,
)  # noqa: F401

__all__ = ["cloud_beat_task_generator"]
