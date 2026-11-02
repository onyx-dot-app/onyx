"""Factory stub for running celery worker / celery beat.
This code is different from the primary/beat stubs because there is no EE version to
fetch. Port over the code in those files if we add an EE version of this worker."""

from celery import Celery

from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    set_is_ee_if_available,
)

set_is_ee_if_available()
app: Celery = fetch_versioned_implementation(
    "onyx.background.celery.apps.heavy",
    "celery_app",
)
