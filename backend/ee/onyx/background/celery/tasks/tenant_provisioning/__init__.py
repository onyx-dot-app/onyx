"""Celery tasks for tenant provisioning checks."""

from ee.onyx.background.celery.tasks.tenant_provisioning.tasks import (  # noqa: F401
    check_available_tenants,
)

__all__ = ["check_available_tenants"]
