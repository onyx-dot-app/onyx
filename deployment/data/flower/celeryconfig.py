broker_url = "redis://cache:6379/15"
broker_result_backend = "redis://cache:6379/14"
broker_transport_options = {
    "priority_steps": [0, 1, 2, 3, 4],
    "sep": ":",
    "queue_order_strategy": "priority",
}
