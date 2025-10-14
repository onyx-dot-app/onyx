from onyx.background.celery.apps.background import celery_app


celery_app.autodiscover_tasks(
    [
        "ee.onyx.background.celery.tasks.doc_permission_syncing",
        "ee.onyx.background.celery.tasks.external_group_syncing",
        "ee.onyx.background.celery.tasks.cleanup",
        "ee.onyx.background.celery.tasks.tenant_provisioning",
        "ee.onyx.background.celery.tasks.query_history",
    ]
)
