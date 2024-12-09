"""Factory stub for running celery worker / celery beat."""
from celery import Celery

from danswer.utils.variable_functionality import fetch_versioned_implementation
from danswer.utils.variable_functionality import set_is_ee_based_on_env_variable

set_is_ee_based_on_env_variable()
app: Celery = fetch_versioned_implementation(
    "danswer.background.celery.apps.primary", "celery_app"
)
