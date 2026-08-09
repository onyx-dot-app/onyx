"""Factory stub for running the user file processing Celery worker."""

from celery import Celery

from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    set_is_ee_based_on_env_variable,
)

set_is_ee_based_on_env_variable()
app: Celery = fetch_versioned_implementation(
    "onyx.background.celery.apps.user_file_processing",
    "celery_app",
)
