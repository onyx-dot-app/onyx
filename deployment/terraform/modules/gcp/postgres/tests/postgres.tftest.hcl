# Plans the module against a mocked provider, so these run without a GCP
# project or credentials. Run with `terraform test` from the module directory.

mock_provider "google" {}

variables {
  name       = "onyx-postgres-prod"
  project_id = "example-project"
  region     = "us-east1"
  network_id = "projects/example-project/global/networks/onyx-vpc"
  password   = "not-a-real-password"
}

run "defaults_are_private_and_encrypted" {
  command = plan

  assert {
    condition     = one(google_sql_database_instance.this.settings[0].ip_configuration).ipv4_enabled == false
    error_message = "The instance must get no public IP."
  }

  assert {
    condition     = one(google_sql_database_instance.this.settings[0].ip_configuration).private_network == var.network_id
    error_message = "The instance must join the peered network through Private Service Access."
  }

  assert {
    condition     = one(google_sql_database_instance.this.settings[0].ip_configuration).ssl_mode == "ENCRYPTED_ONLY"
    error_message = "The server should refuse plaintext; both Onyx drivers encrypt by default."
  }

  assert {
    condition     = google_sql_database_instance.this.settings[0].edition == "ENTERPRISE"
    error_message = "PostgreSQL 16 defaults to ENTERPRISE_PLUS, which rejects db-custom tiers."
  }

  assert {
    condition     = google_sql_database_instance.this.settings[0].disk_type == "PD_SSD" && google_sql_database_instance.this.settings[0].disk_autoresize == true
    error_message = "The data disk should be SSD and grow on its own."
  }

  assert {
    condition     = google_sql_database_instance.this.settings[0].availability_type == "ZONAL"
    error_message = "A standby is opt-in because it roughly doubles cost."
  }
}

run "defaults_protect_the_data" {
  command = plan

  assert {
    condition     = google_sql_database_instance.this.deletion_protection == true
    error_message = "Terraform must refuse to delete the instance by default."
  }

  assert {
    condition     = google_sql_database_instance.this.settings[0].deletion_protection_enabled == true
    error_message = "The API-side guard must be on too, so the console and gcloud cannot delete it either."
  }

  assert {
    condition     = google_sql_database.this[0].deletion_policy == "PREVENT"
    error_message = "The database must not be dropped while protection is on."
  }

  assert {
    condition = alltrue([
      one(google_sql_database_instance.this.settings[0].backup_configuration).enabled,
      one(google_sql_database_instance.this.settings[0].backup_configuration).point_in_time_recovery_enabled,
    ])
    error_message = "Backups and point-in-time recovery should be on."
  }

  assert {
    condition     = one(one(google_sql_database_instance.this.settings[0].backup_configuration).backup_retention_settings).retained_backups == 7
    error_message = "Seven backups should be kept, matching the AWS module's 7 days."
  }
}

run "max_connections_is_raised_for_onyx_pools" {
  command = plan

  assert {
    condition     = [for f in google_sql_database_instance.this.settings[0].database_flags : f.value if f.name == "max_connections"] == ["500"]
    error_message = "max_connections should be set; the Cloud SQL default is too low for Onyx's pools."
  }

  assert {
    condition     = length([for f in google_sql_database_instance.this.settings[0].database_flags : f if f.name == "log_min_duration_statement"]) == 0
    error_message = "Slow-statement logging is opt-in."
  }
}

run "slow_statement_logging_can_be_turned_on" {
  command = plan

  variables {
    log_min_duration_statement_ms = 1000
  }

  assert {
    condition     = [for f in google_sql_database_instance.this.settings[0].database_flags : f.value if f.name == "log_min_duration_statement"] == ["1000"]
    error_message = "log_min_duration_statement_ms should reach the flag."
  }
}

run "the_builtin_postgres_user_gets_the_password" {
  command = plan

  # "postgres" is what the chart and the backend default to. Cloud SQL ships
  # that user, so the module sets its password rather than creating it.
  assert {
    condition     = length(google_sql_user.this) == 0
    error_message = "Creating the built-in postgres user again would fail."
  }

  assert {
    condition     = google_sql_database_instance.this.root_password == var.password
    error_message = "root_password is how the built-in postgres user gets its password."
  }

  assert {
    condition     = output.username == "postgres"
    error_message = "The output reports what Onyx logs in as."
  }
}

run "another_username_creates_a_user" {
  command = plan

  variables {
    username = "onyx"
  }

  assert {
    condition     = google_sql_user.this[0].name == "onyx"
    error_message = "A name Cloud SQL does not ship should be created."
  }

  assert {
    condition     = google_sql_user.this[0].deletion_policy == "ABANDON"
    error_message = "Cloud SQL cannot drop a role that owns Onyx's tables, so destroy must not try."
  }

  assert {
    condition     = google_sql_database_instance.this.root_password == null
    error_message = "The built-in user should not get the password when another user is in use."
  }
}

run "a_database_of_our_own_is_created" {
  command = plan

  assert {
    condition     = google_sql_database.this[0].name == "onyx"
    error_message = "The default database should be created."
  }
}

run "a_database_the_instance_ships_is_not_recreated" {
  command = plan

  variables {
    db_name = "postgres"
  }

  assert {
    condition     = length(google_sql_database.this) == 0
    error_message = "Naming the built-in database should mean use it, not create it."
  }

  assert {
    condition     = output.db_name == "postgres"
    error_message = "The output still reports what Onyx connects to."
  }
}

run "turning_protection_off_allows_a_destroy" {
  command = plan

  variables {
    deletion_protection = false
  }

  assert {
    condition = alltrue([
      google_sql_database_instance.this.deletion_protection == false,
      google_sql_database_instance.this.settings[0].deletion_protection_enabled == false,
    ])
    error_message = "One switch should lift both the Terraform and the API guard."
  }

  assert {
    condition     = google_sql_database.this[0].deletion_policy == "ABANDON"
    error_message = "The instance deletion takes the database with it; dropping it first fails while pods are connected."
  }
}

run "regional_adds_a_standby" {
  command = plan

  variables {
    availability_type = "REGIONAL"
  }

  assert {
    condition     = google_sql_database_instance.this.settings[0].availability_type == "REGIONAL"
    error_message = "REGIONAL should reach the instance."
  }
}

run "maintenance_window_can_be_left_to_google" {
  command = plan

  variables {
    maintenance_window = null
  }

  assert {
    condition     = length(google_sql_database_instance.this.settings[0].maintenance_window) == 0
    error_message = "A null window should set no window."
  }
}

run "labels_reach_the_instance_and_alerts" {
  command = plan

  variables {
    labels = { env = "prod", team = "platform" }
  }

  assert {
    condition     = google_sql_database_instance.this.settings[0].user_labels["env"] == "prod"
    error_message = "Labels should reach the instance."
  }

  assert {
    condition     = google_monitoring_alert_policy.this["cpu"].user_labels["team"] == "platform"
    error_message = "Labels should reach the alerts."
  }
}

run "all_five_alerts_exist_and_stay_silent" {
  command = plan

  assert {
    condition     = toset(keys(google_monitoring_alert_policy.this)) == toset(["cpu", "memory", "disk", "connections", "down"])
    error_message = "The module should create the five alerts that mirror the AWS module."
  }

  assert {
    condition     = alltrue([for p in google_monitoring_alert_policy.this : length(coalesce(p.notification_channels, [])) == 0])
    error_message = "With no channel the alerts must exist but notify nothing, the same as the AWS module."
  }

  assert {
    condition = alltrue([
      for p in google_monitoring_alert_policy.this :
      strcontains(p.conditions[0].condition_threshold[0].filter, "resource.type = \"cloudsql_database\"") &&
      strcontains(p.conditions[0].condition_threshold[0].filter, "resource.labels.database_id = \"example-project:onyx-postgres-prod\"")
    ])
    error_message = "Every alert should watch this instance, identified as <project>:<instance>."
  }

  assert {
    condition     = strcontains(google_monitoring_alert_policy.this["connections"].conditions[0].condition_threshold[0].filter, "cloudsql.googleapis.com/database/postgresql/num_backends")
    error_message = "The connections alert should read num_backends."
  }

  assert {
    condition     = google_monitoring_alert_policy.this["connections"].conditions[0].condition_threshold[0].threshold_value == 400
    error_message = "The connections alert should default to 80% of max_connections."
  }

  assert {
    condition     = google_monitoring_alert_policy.this["connections"].conditions[0].condition_threshold[0].aggregations[0].cross_series_reducer == "REDUCE_SUM"
    error_message = "num_backends is reported per database, so the series must be summed."
  }

  assert {
    condition     = google_monitoring_alert_policy.this["cpu"].conditions[0].condition_threshold[0].threshold_value == 0.8
    error_message = "Cloud SQL reports CPU as a fraction, so 80% must become 0.8."
  }

  assert {
    condition     = google_monitoring_alert_policy.this["down"].conditions[0].condition_threshold[0].evaluation_missing_data == "EVALUATION_MISSING_DATA_ACTIVE"
    error_message = "A server that stops reporting is down too."
  }

  assert {
    condition     = google_monitoring_alert_policy.this["disk"].severity == "CRITICAL"
    error_message = "A full data volume wedges the writer, so it should outrank the other alerts."
  }
}

run "a_channel_wires_every_alert" {
  command = plan

  variables {
    notification_channels = ["projects/example-project/notificationChannels/1234567890"]
  }

  assert {
    condition     = alltrue([for p in google_monitoring_alert_policy.this : length(p.notification_channels) == 1])
    error_message = "Every alert should route to the supplied channel."
  }
}

run "alerts_can_be_turned_off" {
  command = plan

  variables {
    enable_alerts = false
  }

  assert {
    condition     = length(google_monitoring_alert_policy.this) == 0
    error_message = "enable_alerts = false should create no alert policies."
  }
}

run "an_explicit_connections_threshold_wins" {
  command = plan

  variables {
    max_connections             = 1000
    connections_alarm_threshold = 900
  }

  assert {
    condition     = google_monitoring_alert_policy.this["connections"].conditions[0].condition_threshold[0].threshold_value == 900
    error_message = "A supplied threshold should replace the 80% default."
  }
}

# --- Validation ----------------------------------------------------------------

run "rejects_a_missing_password" {
  command = plan

  variables {
    password = null
  }

  expect_failures = [var.password]
}

run "rejects_an_empty_password" {
  command = plan

  variables {
    password = ""
  }

  expect_failures = [var.password]
}

run "rejects_plaintext_connections" {
  command = plan

  variables {
    ssl_mode = "ALLOW_UNENCRYPTED_AND_ENCRYPTED"
  }

  expect_failures = [var.ssl_mode]
}

run "rejects_an_invalid_name" {
  command = plan

  variables {
    name = "Onyx_Postgres"
  }

  expect_failures = [var.name]
}

run "rejects_an_invalid_project_id" {
  command = plan

  variables {
    project_id = "x"
  }

  expect_failures = [var.project_id]
}

run "rejects_a_zone_as_region" {
  command = plan

  variables {
    region = "us-east1-b"
  }

  expect_failures = [var.region]
}

run "rejects_a_network_that_is_not_a_network" {
  command = plan

  variables {
    network_id = "onyx-vpc"
  }

  expect_failures = [var.network_id]
}

run "rejects_an_old_or_foreign_database_version" {
  command = plan

  variables {
    database_version = "MYSQL_8_0"
  }

  expect_failures = [var.database_version]
}

run "rejects_an_enterprise_plus_tier" {
  command = plan

  variables {
    tier = "db-perf-optimized-N-2"
  }

  expect_failures = [var.tier]
}

run "rejects_a_disk_below_the_minimum" {
  command = plan

  variables {
    disk_size_gb = 5
  }

  expect_failures = [var.disk_size_gb]
}

run "rejects_an_unknown_availability_type" {
  command = plan

  variables {
    availability_type = "MULTI_REGION"
  }

  expect_failures = [var.availability_type]
}

run "rejects_a_reserved_database_name" {
  command = plan

  variables {
    db_name = "template1"
  }

  expect_failures = [var.db_name]
}

run "rejects_a_reserved_username" {
  command = plan

  variables {
    username = "cloudsqlsuperuser"
  }

  expect_failures = [var.username]
}

run "rejects_max_connections_outside_the_cloud_sql_range" {
  command = plan

  variables {
    max_connections = 5
  }

  expect_failures = [var.max_connections]
}

run "rejects_a_bad_log_threshold" {
  command = plan

  variables {
    log_min_duration_statement_ms = -5
  }

  expect_failures = [var.log_min_duration_statement_ms]
}

run "rejects_zero_retained_backups" {
  command = plan

  variables {
    backup_retention_count = 0
  }

  expect_failures = [var.backup_retention_count]
}

run "rejects_a_bad_backup_start_time" {
  command = plan

  variables {
    backup_start_time = "3am"
  }

  expect_failures = [var.backup_start_time]
}

run "rejects_a_bad_maintenance_day" {
  command = plan

  # Cloud SQL counts from Monday = 1, so 0 is not a day.
  variables {
    maintenance_window = { day = 0, hour = 4 }
  }

  expect_failures = [var.maintenance_window]
}

run "rejects_uppercase_labels" {
  command = plan

  variables {
    labels = { Env = "Prod" }
  }

  expect_failures = [var.labels]
}

run "rejects_a_cpu_threshold_over_100" {
  command = plan

  variables {
    cpu_alarm_threshold = 150
  }

  expect_failures = [var.cpu_alarm_threshold]
}

run "rejects_a_zero_connections_threshold" {
  command = plan

  variables {
    connections_alarm_threshold = 0
  }

  expect_failures = [var.connections_alarm_threshold]
}

run "outputs_carry_the_connection_details" {
  command = apply

  override_resource {
    target = google_sql_database_instance.this
    values = {
      private_ip_address = "10.20.0.3"
      connection_name    = "example-project:us-east1:onyx-postgres-prod"
      server_ca_cert     = [{ cert = "-----BEGIN CERTIFICATE-----\nnot-a-real-cert\n-----END CERTIFICATE-----" }]
    }
  }

  assert {
    condition     = output.host == "10.20.0.3" && output.private_ip_address == "10.20.0.3"
    error_message = "host should be the private IP Onyx connects to."
  }

  assert {
    condition     = output.port == 5432
    error_message = "Cloud SQL for PostgreSQL listens on 5432."
  }

  assert {
    condition     = startswith(output.server_ca_cert, "-----BEGIN CERTIFICATE-----")
    error_message = "The server CA should come out as a PEM the chart can mount."
  }
}
