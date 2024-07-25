"""Entry point for running celery worker / celery beat."""
from danswer.utils.variable_functionality import fetch_versioned_implementation
from danswer.utils.variable_functionality import set_is_ee_based_on_env_variable


set_is_ee_based_on_env_variable()
celery_app = fetch_versioned_implementation(
    "danswer.background.celery.celery_app", "celery_app"
)
