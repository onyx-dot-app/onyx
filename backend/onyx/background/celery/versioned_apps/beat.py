"""Factory stub for running celery worker / celery beat."""

from celery import Celery

from onyx.background.celery.apps.beat import celery_app
from onyx.utils.variable_functionality import set_is_ee_if_available

set_is_ee_if_available()
app: Celery = celery_app
