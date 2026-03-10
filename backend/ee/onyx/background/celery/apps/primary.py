from onyx.background.celery.apps import app_base
from onyx.background.celery.apps.primary import celery_app


celery_app.autodiscover_tasks(
    app_base.filter_task_modules(
        [
            "ee.onyx.background.celery.tasks.doc_permission_syncing",
            "ee.onyx.background.celery.tasks.external_group_syncing",
            "ee.onyx.background.celery.tasks.cloud",
            "ee.onyx.background.celery.tasks.ttl_management",
            "ee.onyx.background.celery.tasks.usage_reporting",
        ]
    )
)
