locals {
  # Cloud SQL ships a "postgres" database. Asking Terraform to create it fails
  # with "already exists", so naming it is read as "use the database that is
  # already there" rather than as an error.
  builtin_databases = ["postgres"]
  create_database   = !contains(local.builtin_databases, var.db_name)

  # Cloud SQL also ships a "postgres" user. It cannot be created again, but the
  # instance's root_password sets its password, and the provider updates it in
  # place on later changes. Any other name is a user this module creates.
  # "postgres" is the default because it is what the Helm chart and the backend
  # (POSTGRES_USER) fall back to, and it is what the AWS module uses.
  use_builtin_user = var.username == "postgres"

  # Monitoring labels every Cloud SQL series with database_id in the form
  # "<project>:<instance>". Built from inputs, not the instance, so the filter
  # is known at plan time.
  database_id = "${var.project_id}:${var.name}"

  # Alerts share one evaluation shape, chosen to match the AWS module: average
  # over 5 minutes and fire after 15 minutes over the threshold, so a single
  # spike does not page.
  alert_alignment_period = "300s"
  alert_duration         = "900s"

  connections_alarm_threshold = coalesce(var.connections_alarm_threshold, floor(var.max_connections * 0.8))

  alerts = var.enable_alerts ? {
    cpu = {
      display_name = "PostgreSQL ${var.name} CPU utilisation high"
      metric       = "cloudsql.googleapis.com/database/cpu/utilization"
      comparison   = "COMPARISON_GT"
      threshold    = var.cpu_alarm_threshold / 100
      aligner      = "ALIGN_MEAN"
      reducer      = null
      duration     = local.alert_duration
      alignment    = local.alert_alignment_period
      missing_data = null
      severity     = "WARNING"
    }
    memory = {
      display_name = "PostgreSQL ${var.name} memory utilisation high"
      metric       = "cloudsql.googleapis.com/database/memory/utilization"
      comparison   = "COMPARISON_GT"
      threshold    = var.memory_alarm_threshold / 100
      aligner      = "ALIGN_MEAN"
      reducer      = null
      duration     = local.alert_duration
      alignment    = local.alert_alignment_period
      missing_data = null
      severity     = "WARNING"
    }
    # A full data volume wedges the writer. Auto-resize usually gets there
    # first, but it grows in steps and can fall behind a WAL runaway.
    disk = {
      display_name = "PostgreSQL ${var.name} disk nearly full"
      metric       = "cloudsql.googleapis.com/database/disk/utilization"
      comparison   = "COMPARISON_GT"
      threshold    = var.disk_alarm_threshold / 100
      aligner      = "ALIGN_MEAN"
      reducer      = null
      duration     = local.alert_duration
      alignment    = local.alert_alignment_period
      missing_data = null
      severity     = "CRITICAL"
    }
    # A task holding a session across an external call, or a request-cancel
    # leak, saturates the pool and new pods then fail to start. num_backends is
    # reported once per database, so the series are summed per instance.
    connections = {
      display_name = "PostgreSQL ${var.name} connection count high"
      metric       = "cloudsql.googleapis.com/database/postgresql/num_backends"
      comparison   = "COMPARISON_GT"
      threshold    = local.connections_alarm_threshold
      aligner      = "ALIGN_MEAN"
      reducer      = "REDUCE_SUM"
      duration     = local.alert_duration
      alignment    = local.alert_alignment_period
      missing_data = null
      severity     = "WARNING"
    }
    # Stands in for the AWS module's ReadIOPS alarm, which has no useful Cloud
    # SQL equivalent. An unplanned outage keeps the instance state RUNNING and
    # only drops this metric to 0, and a stopped series means the same thing.
    down = {
      display_name = "PostgreSQL ${var.name} server down"
      metric       = "cloudsql.googleapis.com/database/up"
      comparison   = "COMPARISON_LT"
      threshold    = 1
      aligner      = "ALIGN_MAX"
      reducer      = null
      duration     = "300s"
      alignment    = "60s"
      missing_data = "EVALUATION_MISSING_DATA_ACTIVE"
      severity     = "CRITICAL"
    }
  } : {}
}

resource "google_sql_database_instance" "this" {
  name             = var.name
  project          = var.project_id
  region           = var.region
  database_version = var.database_version

  # Only meaningful when username is "postgres"; see local.use_builtin_user.
  root_password = local.use_builtin_user ? var.password : null

  # Terraform-side guard. settings.deletion_protection_enabled below is the
  # API-side one that also stops the console and gcloud. To destroy, set
  # deletion_protection = false and apply before running destroy.
  deletion_protection = var.deletion_protection

  settings {
    # Pinned: PostgreSQL 16 and later default to ENTERPRISE_PLUS, which rejects
    # the db-custom-* tiers this module takes.
    edition           = "ENTERPRISE"
    tier              = var.tier
    availability_type = var.availability_type

    disk_type       = "PD_SSD"
    disk_size       = var.disk_size_gb
    disk_autoresize = true
    # No ignore_changes on disk_size: the provider drops the diff itself when
    # auto-resize has grown the disk past the configured size.

    deletion_protection_enabled = var.deletion_protection
    user_labels                 = var.labels

    ip_configuration {
      # Private IP only. private_network must already be peered through Private
      # Service Access; pass the vpc module's private_service_access_network_id
      # so the instance waits for the peering.
      ipv4_enabled    = false
      private_network = var.network_id

      # Both Onyx drivers encrypt by default, so the server can refuse plaintext:
      # psycopg2 uses libpq's default sslmode=prefer, and asyncpg falls back to
      # "prefer" over TCP when Onyx passes ssl=None (POSTGRES_SSLMODE unset).
      # Setting POSTGRES_SSLMODE=disable breaks the sync engine against this.
      ssl_mode = var.ssl_mode
    }

    backup_configuration {
      enabled                        = true
      start_time                     = var.backup_start_time
      point_in_time_recovery_enabled = true
      # ENTERPRISE edition caps this at 7 days.
      transaction_log_retention_days = 7

      backup_retention_settings {
        retained_backups = var.backup_retention_count
        retention_unit   = "COUNT"
      }
    }

    dynamic "maintenance_window" {
      for_each = var.maintenance_window != null ? [var.maintenance_window] : []
      content {
        day          = maintenance_window.value.day
        hour         = maintenance_window.value.hour
        update_track = maintenance_window.value.update_track
      }
    }

    insights_config {
      query_insights_enabled = true
      # Off: client addresses and application tags are not needed to find a
      # slow query, and client addresses are personal data in some regions.
      record_client_address   = false
      record_application_tags = false
    }

    # Onyx opens a pool per process: pods x workers x (pool + overflow). The
    # Cloud SQL default scales with memory and is far too low for that.
    # Changing this flag restarts the instance.
    database_flags {
      name  = "max_connections"
      value = tostring(var.max_connections)
    }

    dynamic "database_flags" {
      for_each = var.log_min_duration_statement_ms != null ? [var.log_min_duration_statement_ms] : []
      content {
        name  = "log_min_duration_statement"
        value = tostring(database_flags.value)
      }
    }
  }
}

resource "google_sql_database" "this" {
  count = local.create_database ? 1 : 0

  name      = var.db_name
  project   = var.project_id
  instance  = google_sql_database_instance.this.name
  charset   = "UTF8"
  collation = "en_US.UTF8"

  # PREVENT refuses to drop the data. When protection is off, ABANDON lets the
  # instance deletion take the database with it: dropping it first fails while
  # Onyx pods still hold connections.
  deletion_policy = var.deletion_protection ? "PREVENT" : "ABANDON"
}

resource "google_sql_user" "this" {
  count = local.use_builtin_user ? 0 : 1

  name     = var.username
  project  = var.project_id
  instance = google_sql_database_instance.this.name
  password = var.password

  # Onyx's migrations make this user own every table, and Cloud SQL cannot
  # drop a role that owns objects. The instance deletion removes it instead.
  deletion_policy = "ABANDON"
}

resource "google_monitoring_alert_policy" "this" {
  for_each = local.alerts

  project      = var.project_id
  display_name = each.value.display_name
  combiner     = "OR"
  severity     = each.value.severity
  user_labels  = var.labels

  # Empty means the alert exists and records incidents but notifies nobody,
  # the same as the AWS module with no alarm_actions.
  notification_channels = var.notification_channels

  conditions {
    display_name = each.value.display_name

    condition_threshold {
      filter          = "resource.type = \"cloudsql_database\" AND resource.labels.database_id = \"${local.database_id}\" AND metric.type = \"${each.value.metric}\""
      comparison      = each.value.comparison
      threshold_value = each.value.threshold
      duration        = each.value.duration

      evaluation_missing_data = each.value.missing_data

      aggregations {
        alignment_period     = each.value.alignment
        per_series_aligner   = each.value.aligner
        cross_series_reducer = each.value.reducer
        group_by_fields      = each.value.reducer != null ? ["resource.label.database_id"] : null
      }

      trigger {
        count = 1
      }
    }
  }
}
