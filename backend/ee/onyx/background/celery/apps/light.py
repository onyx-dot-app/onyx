from onyx.background.celery.apps import app_base
from onyx.background.celery.apps.light import celery_app

celery_app.autodiscover_tasks(
    app_base.filter_task_modules(
        [
            "ee.onyx.background.celery.tasks.doc_permission_syncing",
            "ee.onyx.background.celery.tasks.external_group_syncing",
            # perform_ttl_management_task routes to the chat_ttl_deletion queue,
            # which the light worker consumes — it must be registered here, not
            # just on the primary app, or the worker rejects it as unregistered.
            "ee.onyx.background.celery.tasks.ttl_management",
        ]
    )
)
