import onyx.background.celery.configs.base as shared_config
from onyx.configs.app_configs import CELERY_WORKER_DOCFETCHING_CONCURRENCY

broker_url = shared_config.broker_url
broker_connection_retry_on_startup = shared_config.broker_connection_retry_on_startup
broker_pool_limit = shared_config.broker_pool_limit
broker_transport_options = shared_config.broker_transport_options

redis_socket_keepalive = shared_config.redis_socket_keepalive
redis_retry_on_timeout = shared_config.redis_retry_on_timeout
redis_backend_health_check_interval = shared_config.redis_backend_health_check_interval

result_backend = shared_config.result_backend
result_expires = shared_config.result_expires  # 86400 seconds is the default

task_default_priority = shared_config.task_default_priority
task_acks_late = shared_config.task_acks_late

# Docfetching worker configuration
worker_concurrency = CELERY_WORKER_DOCFETCHING_CONCURRENCY
worker_pool = "threads"
worker_prefetch_multiplier = 1
