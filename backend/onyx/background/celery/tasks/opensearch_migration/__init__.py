"""Celery tasks for OpenSearch migration."""

from onyx.background.celery.tasks.opensearch_migration.tasks import (  # noqa: F401
    migrate_chunks_from_vespa_to_opensearch_task,
)

__all__ = ["migrate_chunks_from_vespa_to_opensearch_task"]
