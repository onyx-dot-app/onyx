"""Factory stub for running celery worker / celery beat."""
from celery import Celery

from onyx.utils.variable_functionality import set_is_ee_based_on_env_variable

set_is_ee_based_on_env_variable()


def get_app() -> Celery:
    from onyx.background.celery.apps.monitoring import celery_app

    return celery_app


app = get_app()
