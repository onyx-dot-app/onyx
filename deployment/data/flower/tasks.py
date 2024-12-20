from celery import Celery

app = Celery("flower")
app.config_from_object("celeryconfig")
