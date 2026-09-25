# Plans the module against a mocked provider, so these run without a GCP
# project or credentials. Run with `terraform test` from the module directory.

mock_provider "google" {}

variables {
  name       = "onyx-redis-prod"
  project_id = "example-project"
  region     = "us-east1"
  network_id = "projects/example-project/global/networks/onyx-vpc"
}

run "defaults_are_private_authenticated_and_protected" {
  command = plan

  assert {
    condition     = google_redis_instance.this.connect_mode == "PRIVATE_SERVICE_ACCESS"
    error_message = "The instance should sit in the Private Service Access range."
  }

  assert {
    condition     = google_redis_instance.this.authorized_network == var.network_id
    error_message = "The instance should be attached to the network passed in."
  }

  assert {
    condition     = google_redis_instance.this.auth_enabled == true
    error_message = "Without AUTH anything in the network can read and flush the broker."
  }

  assert {
    condition     = google_redis_instance.this.deletion_protection == true
    error_message = "Deletion protection should be on by default."
  }

  assert {
    condition     = google_redis_instance.this.read_replicas_mode == "READ_REPLICAS_DISABLED"
    error_message = "Onyx sends all traffic to the primary."
  }
}

run "default_shape_is_ha_redis_7" {
  command = plan

  assert {
    condition     = google_redis_instance.this.tier == "STANDARD_HA"
    error_message = "A single BASIC node loses every queued task on restart."
  }

  assert {
    condition     = google_redis_instance.this.memory_size_gb == 5
    error_message = "5 GiB is the default size."
  }

  assert {
    condition     = google_redis_instance.this.redis_version == "REDIS_7_2"
    error_message = "Redis 7.2 is the default engine."
  }
}

run "eviction_leaves_broker_keys_alone" {
  command = plan

  assert {
    condition     = google_redis_instance.this.redis_configs["maxmemory-policy"] == "volatile-lru"
    error_message = "volatile-lru only evicts keys with a TTL, which Celery broker keys do not have."
  }
}

run "rdb_snapshots_hourly_by_default" {
  command = plan

  assert {
    condition     = google_redis_instance.this.persistence_config[0].persistence_mode == "RDB"
    error_message = "RDB persistence should be on by default."
  }

  assert {
    condition     = google_redis_instance.this.persistence_config[0].rdb_snapshot_period == "ONE_HOUR"
    error_message = "Snapshots should run every hour by default."
  }
}

run "persistence_can_be_turned_off" {
  command = plan

  variables {
    persistence_enabled = false
  }

  assert {
    condition     = google_redis_instance.this.persistence_config[0].persistence_mode == "DISABLED"
    error_message = "Turning persistence off should reach the instance."
  }

  assert {
    condition     = google_redis_instance.this.persistence_config[0].rdb_snapshot_period == null
    error_message = "A snapshot period with persistence off is meaningless."
  }
}

run "plaintext_by_default" {
  command = plan

  assert {
    condition     = google_redis_instance.this.transit_encryption_mode == "DISABLED"
    error_message = "TLS is off by default."
  }

  assert {
    condition     = output.redis_url_scheme == "redis"
    error_message = "Without TLS the scheme is redis."
  }
}

run "tls_switches_the_scheme" {
  command = plan

  variables {
    transit_encryption_enabled = true
  }

  assert {
    condition     = google_redis_instance.this.transit_encryption_mode == "SERVER_AUTHENTICATION"
    error_message = "Enabling TLS should reach the instance."
  }

  assert {
    condition     = output.redis_url_scheme == "rediss"
    error_message = "Celery needs the rediss scheme to speak TLS."
  }
}

run "labels_reach_instance_and_alerts" {
  command = plan

  variables {
    labels = { env = "prod" }
  }

  assert {
    condition     = google_redis_instance.this.labels["env"] == "prod"
    error_message = "Labels should reach the instance."
  }

  assert {
    condition     = google_monitoring_alert_policy.evicted_keys[0].user_labels["env"] == "prod"
    error_message = "Labels should reach the alert policies."
  }
}

run "maintenance_window" {
  command = plan

  variables {
    maintenance_day        = "TUESDAY"
    maintenance_start_hour = 3
  }

  assert {
    condition     = google_redis_instance.this.maintenance_policy[0].weekly_maintenance_window[0].day == "TUESDAY"
    error_message = "The maintenance day should reach the instance."
  }

  assert {
    condition     = google_redis_instance.this.maintenance_policy[0].weekly_maintenance_window[0].start_time[0].hours == 3
    error_message = "The maintenance hour should reach the instance."
  }
}

run "five_alerts_exist_and_stay_silent" {
  command = plan

  assert {
    condition = alltrue([
      length(google_monitoring_alert_policy.memory_high) == 1,
      length(google_monitoring_alert_policy.memory_critical) == 1,
      length(google_monitoring_alert_policy.cpu) == 1,
      length(google_monitoring_alert_policy.connected_clients) == 1,
      length(google_monitoring_alert_policy.evicted_keys) == 1,
    ])
    error_message = "All five alert policies should exist by default."
  }

  assert {
    condition = alltrue([
      length(google_monitoring_alert_policy.memory_high[0].notification_channels) == 0,
      length(google_monitoring_alert_policy.memory_critical[0].notification_channels) == 0,
      length(google_monitoring_alert_policy.cpu[0].notification_channels) == 0,
      length(google_monitoring_alert_policy.connected_clients[0].notification_channels) == 0,
      length(google_monitoring_alert_policy.evicted_keys[0].notification_channels) == 0,
    ])
    error_message = "With no channels the alerts must exist but notify nothing."
  }
}

run "alerts_watch_the_right_metrics" {
  command = plan

  assert {
    condition     = strcontains(google_monitoring_alert_policy.memory_high[0].conditions[0].condition_threshold[0].filter, "redis.googleapis.com/stats/memory/usage_ratio")
    error_message = "The memory alert should watch the usage ratio."
  }

  assert {
    condition     = google_monitoring_alert_policy.memory_high[0].conditions[0].condition_threshold[0].threshold_value == 0.8
    error_message = "The usage ratio is a fraction, so 80% is 0.8."
  }

  assert {
    condition     = google_monitoring_alert_policy.memory_critical[0].conditions[0].condition_threshold[0].threshold_value == 0.9
    error_message = "The critical usage ratio defaults to 0.9."
  }

  assert {
    condition     = google_monitoring_alert_policy.cpu[0].conditions[0].condition_threshold[0].aggregations[0].per_series_aligner == "ALIGN_RATE"
    error_message = "CPU is reported as CPU-seconds, so it needs a rate to become a fraction of a core."
  }

  assert {
    condition     = strcontains(google_monitoring_alert_policy.cpu[0].conditions[0].condition_threshold[0].filter, "stats/cpu_utilization_main_thread")
    error_message = "Redis runs commands on one thread, so the main thread is the CPU signal."
  }

  assert {
    condition     = google_monitoring_alert_policy.evicted_keys[0].conditions[0].condition_threshold[0].aggregations[0].per_series_aligner == "ALIGN_SUM"
    error_message = "Evictions are a count over the window, not an average."
  }

  assert {
    condition     = strcontains(google_monitoring_alert_policy.connected_clients[0].conditions[0].condition_threshold[0].filter, "resource.type = \"redis_instance\"")
    error_message = "Alerts should filter on the Memorystore resource type."
  }

  assert {
    condition     = strcontains(google_monitoring_alert_policy.connected_clients[0].conditions[0].condition_threshold[0].filter, "instances/)?onyx-redis-prod\")")
    error_message = "Alerts should be scoped to this instance."
  }
}

run "alerts_route_to_channels" {
  command = plan

  variables {
    notification_channels = ["projects/example-project/notificationChannels/123"]
  }

  assert {
    condition     = google_monitoring_alert_policy.memory_critical[0].notification_channels == tolist(["projects/example-project/notificationChannels/123"])
    error_message = "Alerts should route to the channels passed in."
  }

  assert {
    condition     = google_monitoring_alert_policy.evicted_keys[0].notification_channels == tolist(["projects/example-project/notificationChannels/123"])
    error_message = "Alerts should route to the channels passed in."
  }
}

run "alerts_can_be_turned_off" {
  command = plan

  variables {
    enable_alerts = false
  }

  assert {
    condition = alltrue([
      length(google_monitoring_alert_policy.memory_high) == 0,
      length(google_monitoring_alert_policy.memory_critical) == 0,
      length(google_monitoring_alert_policy.cpu) == 0,
      length(google_monitoring_alert_policy.connected_clients) == 0,
      length(google_monitoring_alert_policy.evicted_keys) == 0,
    ])
    error_message = "enable_alerts = false should create no alert policies."
  }
}

run "accepts_the_smallest_basic_instance" {
  command = plan

  variables {
    tier           = "BASIC"
    memory_size_gb = 1
  }

  assert {
    condition     = google_redis_instance.this.memory_size_gb == 1
    error_message = "Memorystore accepts 1 GiB."
  }
}

run "accepts_noeviction" {
  command = plan

  variables {
    maxmemory_policy = "noeviction"
  }

  assert {
    condition     = google_redis_instance.this.redis_configs["maxmemory-policy"] == "noeviction"
    error_message = "noeviction never drops broker keys and should stay selectable."
  }
}

run "rejects_an_allkeys_policy" {
  command = plan

  variables {
    maxmemory_policy = "allkeys-lru"
  }

  expect_failures = [var.maxmemory_policy]
}

run "rejects_an_unknown_policy" {
  command = plan

  variables {
    maxmemory_policy = "VolatileLRU"
  }

  expect_failures = [var.maxmemory_policy]
}

run "rejects_an_uppercase_name" {
  command = plan

  variables {
    name = "Onyx-Redis"
  }

  expect_failures = [var.name]
}

run "rejects_a_name_starting_with_a_digit" {
  command = plan

  variables {
    name = "1redis"
  }

  expect_failures = [var.name]
}

run "rejects_a_name_ending_with_a_hyphen" {
  command = plan

  variables {
    name = "onyx-redis-"
  }

  expect_failures = [var.name]
}

run "rejects_a_name_over_40_characters" {
  command = plan

  variables {
    name = "a234567890123456789012345678901234567890x"
  }

  expect_failures = [var.name]
}

run "rejects_a_network_name_instead_of_an_id" {
  command = plan

  variables {
    network_id = "onyx-vpc"
  }

  expect_failures = [var.network_id]
}

run "rejects_an_unknown_tier" {
  command = plan

  variables {
    tier = "STANDARD"
  }

  expect_failures = [var.tier]
}

run "rejects_zero_memory" {
  command = plan

  variables {
    memory_size_gb = 0
  }

  expect_failures = [var.memory_size_gb]
}

run "rejects_memory_over_300" {
  command = plan

  variables {
    memory_size_gb = 301
  }

  expect_failures = [var.memory_size_gb]
}

run "rejects_fractional_memory" {
  command = plan

  variables {
    memory_size_gb = 2.5
  }

  expect_failures = [var.memory_size_gb]
}

run "rejects_redis_6" {
  command = plan

  variables {
    redis_version = "REDIS_6_X"
  }

  expect_failures = [var.redis_version]
}

run "rejects_an_unknown_snapshot_period" {
  command = plan

  variables {
    rdb_snapshot_period = "ONE_DAY"
  }

  expect_failures = [var.rdb_snapshot_period]
}

run "rejects_a_lowercase_maintenance_day" {
  command = plan

  variables {
    maintenance_day = "sunday"
  }

  expect_failures = [var.maintenance_day]
}

run "rejects_a_maintenance_hour_of_24" {
  command = plan

  variables {
    maintenance_start_hour = 24
  }

  expect_failures = [var.maintenance_start_hour]
}

run "rejects_uppercase_labels" {
  command = plan

  variables {
    labels = { Env = "Prod" }
  }

  expect_failures = [var.labels]
}

run "rejects_a_critical_threshold_below_the_warning_one" {
  command = plan

  variables {
    memory_high_threshold_percent     = 90
    memory_critical_threshold_percent = 80
  }

  expect_failures = [var.memory_critical_threshold_percent]
}

run "rejects_a_client_threshold_above_maxclients" {
  command = plan

  variables {
    connected_clients_threshold = 70000
  }

  expect_failures = [var.connected_clients_threshold]
}

run "rejects_a_negative_eviction_threshold" {
  command = plan

  variables {
    evicted_keys_threshold = -1
  }

  expect_failures = [var.evicted_keys_threshold]
}
