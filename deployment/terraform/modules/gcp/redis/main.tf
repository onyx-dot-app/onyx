# Memorystore for Redis, not Memorystore for Redis Cluster or Valkey. Onyx
# needs one endpoint with numbered databases: it keeps app state in DB 0, the
# Celery result backend in DB 14 and the Celery broker in DB 15. The cluster
# products shard keys and only have DB 0, so Celery's first multi-key publish
# fails with CROSSSLOT. That is the same reason Azure has to run Managed Redis
# on the NoCluster policy. Memorystore for Redis is a primary with an optional
# replica, and has the default 16 databases.

locals {
  alert_count = var.enable_alerts ? 1 : 0

  # Match both the full instance path and the bare instance ID, so a change in
  # which form the metric carries does not make every alert silent.
  instance_filter = join(" AND ", [
    "resource.type = \"redis_instance\"",
    "resource.labels.project_id = \"${var.project_id}\"",
    "resource.labels.region = \"${var.region}\"",
    "resource.labels.instance_id = monitoring.regex.full_match(\"(projects/.+/locations/.+/instances/)?${var.name}\")",
  ])
}

resource "google_redis_instance" "this" {
  name           = var.name
  project        = var.project_id
  region         = var.region
  tier           = var.tier
  memory_size_gb = var.memory_size_gb
  redis_version  = var.redis_version

  # Private Service Access puts the instance in the VPC's peered service range,
  # the same path Cloud SQL uses, instead of a peering per instance.
  connect_mode       = "PRIVATE_SERVICE_ACCESS"
  authorized_network = var.network_id
  reserved_ip_range  = var.reserved_ip_range

  # Not a variable. Without AUTH, any pod or VM in the network can read and
  # flush the broker.
  auth_enabled = true

  transit_encryption_mode = var.transit_encryption_enabled ? "SERVER_AUTHENTICATION" : "DISABLED"

  # Onyx sends all traffic to the primary. The mode can only be set at creation.
  read_replicas_mode = "READ_REPLICAS_DISABLED"

  redis_configs = {
    maxmemory-policy = var.maxmemory_policy
  }

  persistence_config {
    persistence_mode    = var.persistence_enabled ? "RDB" : "DISABLED"
    rdb_snapshot_period = var.persistence_enabled ? var.rdb_snapshot_period : null
  }

  maintenance_policy {
    weekly_maintenance_window {
      day = var.maintenance_day
      start_time {
        hours   = var.maintenance_start_hour
        minutes = 0
        seconds = 0
        nanos   = 0
      }
    }
  }

  deletion_protection = var.deletion_protection

  labels = var.labels
}

# Memory is the failure mode that actually takes a broker down: keys that never
# expire climb to the limit, eviction cannot free anything, and Redis starts
# rejecting writes, at which point the whole Celery fleet crashloops at once.
resource "google_monitoring_alert_policy" "memory_high" {
  count = local.alert_count

  project               = var.project_id
  display_name          = "${var.name}-memory-high"
  combiner              = "OR"
  severity              = "WARNING"
  notification_channels = var.notification_channels
  user_labels           = var.labels

  documentation {
    content = "Memorystore ${var.name} memory usage high."
  }

  conditions {
    display_name = "Memory usage ratio above ${var.memory_high_threshold_percent}%"

    condition_threshold {
      filter          = "${local.instance_filter} AND metric.type = \"redis.googleapis.com/stats/memory/usage_ratio\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.memory_high_threshold_percent / 100
      duration        = "900s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }
}

resource "google_monitoring_alert_policy" "memory_critical" {
  count = local.alert_count

  project               = var.project_id
  display_name          = "${var.name}-memory-critical"
  combiner              = "OR"
  severity              = "CRITICAL"
  notification_channels = var.notification_channels
  user_labels           = var.labels

  documentation {
    content = "Memorystore ${var.name} memory usage critical, writes may be rejected."
  }

  conditions {
    display_name = "Memory usage ratio above ${var.memory_critical_threshold_percent}%"

    condition_threshold {
      filter          = "${local.instance_filter} AND metric.type = \"redis.googleapis.com/stats/memory/usage_ratio\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.memory_critical_threshold_percent / 100
      duration        = "900s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }
}

# Redis runs commands on one thread, so the main thread saturates long before
# the node does. The metric is CPU-seconds, so its rate is the fraction of one
# core, summed across the user/system and parent/child series.
resource "google_monitoring_alert_policy" "cpu" {
  count = local.alert_count

  project               = var.project_id
  display_name          = "${var.name}-cpu-high"
  combiner              = "OR"
  severity              = "WARNING"
  notification_channels = var.notification_channels
  user_labels           = var.labels

  documentation {
    content = "Memorystore ${var.name} main thread CPU high."
  }

  conditions {
    display_name = "Main thread CPU above ${var.cpu_threshold_percent}% of one core"

    condition_threshold {
      filter          = "${local.instance_filter} AND metric.type = \"redis.googleapis.com/stats/cpu_utilization_main_thread\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.cpu_threshold_percent / 100
      duration        = "900s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.labels.instance_id", "resource.labels.node_id", "metric.labels.role"]
      }
    }
  }
}

resource "google_monitoring_alert_policy" "connected_clients" {
  count = local.alert_count

  project               = var.project_id
  display_name          = "${var.name}-connected-clients-high"
  combiner              = "OR"
  severity              = "WARNING"
  notification_channels = var.notification_channels
  user_labels           = var.labels

  documentation {
    content = "Memorystore ${var.name} is near its fixed 65000 client limit. New Onyx connections will be refused past it."
  }

  conditions {
    display_name = "Connected clients above ${var.connected_clients_threshold}"

    condition_threshold {
      filter          = "${local.instance_filter} AND metric.type = \"redis.googleapis.com/clients/connected\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.connected_clients_threshold
      duration        = "900s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }
}

resource "google_monitoring_alert_policy" "evicted_keys" {
  count = local.alert_count

  project               = var.project_id
  display_name          = "${var.name}-evicted-keys"
  combiner              = "OR"
  severity              = "CRITICAL"
  notification_channels = var.notification_channels
  user_labels           = var.labels

  documentation {
    content = "Memorystore ${var.name} is evicting keys, which for a Celery broker can mean dropped tasks."
  }

  conditions {
    display_name = "Evicted keys above ${var.evicted_keys_threshold} per 5 minutes"

    condition_threshold {
      filter          = "${local.instance_filter} AND metric.type = \"redis.googleapis.com/stats/evicted_keys\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.evicted_keys_threshold
      duration        = "0s"

      # A count over the window, not an average.
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }
}
