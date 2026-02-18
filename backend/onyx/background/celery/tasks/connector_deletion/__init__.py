"""Celery tasks for connector deletion."""

from onyx.background.celery.tasks.connector_deletion.tasks import (  # noqa: F401
    check_for_connector_deletion_task,
)

__all__ = ["check_for_connector_deletion_task"]
