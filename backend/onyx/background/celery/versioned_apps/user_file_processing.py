"""Factory stub for running the user file processing Celery worker."""

from celery import Celery

from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    set_is_ee_if_available,
)

set_is_ee_if_available()
app: Celery = fetch_versioned_implementation(
    "onyx.background.celery.apps.user_file_processing",
    "celery_app",
)
