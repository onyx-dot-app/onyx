# docs: https://docs.celeryq.dev/en/stable/userguide/configuration.html
from danswer.configs.app_configs import REDIS_DB_NUMBER_CELERY
from danswer.configs.app_configs import REDIS_HOST
from danswer.configs.app_configs import REDIS_PASSWORD
from danswer.configs.app_configs import REDIS_PORT
from danswer.configs.app_configs import REDIS_SSL
from danswer.configs.app_configs import REDIS_SSL_CA_CERTS
from danswer.configs.app_configs import REDIS_SSL_CERT_REQS
from danswer.configs.constants import DanswerCeleryPriority

CELERY_SEPARATOR = ":"

CELERY_PASSWORD_PART = ""
if REDIS_PASSWORD:
    CELERY_PASSWORD_PART = f":{REDIS_PASSWORD}@"

REDIS_SCHEME = "redis"

# SSL-specific query parameters for Redis URL
SSL_QUERY_PARAMS = ""
if REDIS_SSL:
    REDIS_SCHEME = "rediss"
    SSL_QUERY_PARAMS = f"?ssl_cert_reqs={REDIS_SSL_CERT_REQS}"
    if REDIS_SSL_CA_CERTS:
        SSL_QUERY_PARAMS += f"&ssl_ca_certs={REDIS_SSL_CA_CERTS}"

# example celery_broker_url: "redis://:password@localhost:6379/15"
broker_url = f"{REDIS_SCHEME}://{CELERY_PASSWORD_PART}{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB_NUMBER_CELERY}{SSL_QUERY_PARAMS}"

result_backend = f"{REDIS_SCHEME}://{CELERY_PASSWORD_PART}{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB_NUMBER_CELERY}{SSL_QUERY_PARAMS}"

# NOTE: prefetch 4 is significantly faster than prefetch 1 for small tasks
# however, prefetching is bad when tasks are lengthy as those tasks
# can stall other tasks.
worker_prefetch_multiplier = 4

broker_transport_options = {
    "priority_steps": list(range(len(DanswerCeleryPriority))),
    "sep": CELERY_SEPARATOR,
    "queue_order_strategy": "priority",
}

task_default_priority = DanswerCeleryPriority.MEDIUM
task_acks_late = True
