from onyx.background.celery.apps.monitoring import celery_app

celery_app.autodiscover_tasks(
    [
        "ee.onyx.background.celery.tasks.tenant_provisioning",
    ]
)
