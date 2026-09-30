variable "name" {
  type        = string
  description = "Name of the Cloud SQL instance and the alerts named after it. Cloud SQL holds a deleted instance's name for up to a week."

  validation {
    condition     = can(regex("^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$", var.name))
    error_message = "name must be 1-63 characters of lowercase letters, digits and hyphens, must start with a letter and must not end with a hyphen."
  }
}

variable "project_id" {
  type        = string
  description = "Project that holds the instance and its alerts"

  validation {
    condition     = can(regex("^([a-z0-9.-]+:)?[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a GCP project ID: 6-30 lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "region" {
  type        = string
  description = "Region for the instance, for example \"us-east1\""

  validation {
    condition     = can(regex("^[a-z]+-[a-z]+[0-9]+$", var.region))
    error_message = "region must be a GCP region such as \"us-east1\", not a zone."
  }
}

# The instance gets no public IP, so this network is its only way in.
variable "network_id" {
  type        = string
  description = "VPC network the instance joins through Private Service Access. Pass the vpc module's private_service_access_network_id so the instance waits for the peering."

  validation {
    condition     = can(regex("projects/[^/]+/global/networks/[^/]+$", var.network_id))
    error_message = "network_id must be a network ID or self link ending in \"projects/<project>/global/networks/<name>\"."
  }
}

variable "database_version" {
  type        = string
  description = "Cloud SQL PostgreSQL version, for example \"POSTGRES_16\""
  default     = "POSTGRES_16"

  validation {
    condition     = can(regex("^POSTGRES_(1[4-9]|[2-9][0-9])$", var.database_version))
    error_message = "database_version must be POSTGRES_14 or later, for example \"POSTGRES_16\"."
  }
}

# The module pins the ENTERPRISE edition, which takes custom and shared-core
# tiers only. The db-perf-optimized-* tiers belong to ENTERPRISE_PLUS.
variable "tier" {
  type        = string
  description = "Machine tier. db-custom-<vCPUs>-<MiB>, for example \"db-custom-2-8192\" for 2 vCPUs and 8 GiB. Shared-core tiers carry no SLA."
  default     = "db-custom-2-8192"

  validation {
    condition     = can(regex("^db-(custom-[0-9]+-[0-9]+|f1-micro|g1-small)$", var.tier))
    error_message = "tier must be db-custom-<vCPUs>-<MiB> (for example \"db-custom-2-8192\"), db-f1-micro or db-g1-small. The module runs the ENTERPRISE edition, which takes no other tiers."
  }
}

variable "disk_size_gb" {
  type        = number
  description = "Initial data disk size in GB. The disk grows on its own as it fills and can never shrink."
  default     = 50

  validation {
    condition     = var.disk_size_gb >= 10 && floor(var.disk_size_gb) == var.disk_size_gb
    error_message = "disk_size_gb must be a whole number of at least 10 (the Cloud SQL minimum for PD_SSD)."
  }
}

variable "availability_type" {
  type        = string
  description = "ZONAL runs one instance. REGIONAL adds a standby in a second zone, survives a zone outage and roughly doubles cost."
  default     = "ZONAL"

  validation {
    condition     = contains(["ZONAL", "REGIONAL"], var.availability_type)
    error_message = "availability_type must be ZONAL or REGIONAL."
  }
}

variable "db_name" {
  type        = string
  description = "Database Onyx connects to. \"postgres\" uses the database Cloud SQL ships instead of creating one. Onyx reads it from POSTGRES_DB, which defaults to \"postgres\". A change on an existing instance creates the new database and leaves the old one, because Cloud SQL cannot drop a database with live connections and the resource abandons it on destroy; drop it by hand. With deletion_protection on, the apply fails instead."
  default     = "onyx"

  validation {
    condition     = can(regex("^[a-z_][a-z0-9_]{0,62}$", var.db_name))
    error_message = "db_name must be 1-63 characters of lowercase letters, digits and underscores, and must not start with a digit."
  }

  validation {
    condition     = !contains(["cloudsqladmin", "template0", "template1"], var.db_name)
    error_message = "db_name cannot be cloudsqladmin, template0 or template1. Cloud SQL reserves them."
  }
}

variable "username" {
  type        = string
  description = "Login Onyx connects as. \"postgres\" sets the password of the user Cloud SQL ships; any other name creates a user. Both are members of cloudsqlsuperuser. A change on an existing instance creates the new login and leaves the old one, because Cloud SQL cannot drop a role that owns objects and the resource abandons it on destroy; remove it by hand."
  default     = "postgres"

  validation {
    condition     = can(regex("^[a-z_][a-z0-9_]{0,62}$", var.username))
    error_message = "username must be 1-63 characters of lowercase letters, digits and underscores, and must not start with a digit."
  }

  validation {
    condition     = !startswith(var.username, "cloudsql") && !startswith(var.username, "pg_")
    error_message = "username cannot start with \"cloudsql\" or \"pg_\". Cloud SQL and PostgreSQL reserve those names."
  }
}

variable "password" {
  type        = string
  description = "Password for username"
  sensitive   = true

  validation {
    condition     = try(length(var.password) >= 8, false)
    error_message = "password must be set and at least 8 characters. A database with no password cannot be reached by Onyx and should not exist."
  }
}

variable "ssl_mode" {
  type        = string
  description = "How the server enforces TLS. ENCRYPTED_ONLY refuses plaintext and works with Onyx's default settings. TRUSTED_CLIENT_CERTIFICATE_REQUIRED also needs POSTGRES_SSLCERT and POSTGRES_SSLKEY on every pod."
  default     = "ENCRYPTED_ONLY"

  validation {
    condition     = contains(["ENCRYPTED_ONLY", "TRUSTED_CLIENT_CERTIFICATE_REQUIRED"], var.ssl_mode)
    error_message = "ssl_mode must be ENCRYPTED_ONLY or TRUSTED_CLIENT_CERTIFICATE_REQUIRED. ALLOW_UNENCRYPTED_AND_ENCRYPTED is refused: Onyx encrypts by default, so plaintext is never needed."
  }
}

# Onyx holds a pool per process, so the connection count grows with pods and
# workers, not with users. 500 matches the AWS module's connection alarm.
variable "max_connections" {
  type        = number
  description = "max_connections database flag. Size it to pods x workers x (pool size + overflow). Changing it restarts the instance."
  default     = 500

  validation {
    condition     = var.max_connections >= 14 && var.max_connections <= 262142 && floor(var.max_connections) == var.max_connections
    error_message = "max_connections must be a whole number from 14 to 262142 (the Cloud SQL range)."
  }
}

variable "log_min_duration_statement_ms" {
  type        = number
  description = "Log statements slower than this many milliseconds. Null leaves the flag unset, which logs none."
  default     = null

  validation {
    condition     = var.log_min_duration_statement_ms == null || try(var.log_min_duration_statement_ms >= -1 && floor(var.log_min_duration_statement_ms) == var.log_min_duration_statement_ms, false)
    error_message = "log_min_duration_statement_ms must be null, -1 (off) or a whole number of milliseconds."
  }
}

variable "backup_retention_count" {
  type        = number
  description = "Number of daily automated backups to keep"
  default     = 7

  validation {
    condition     = var.backup_retention_count >= 1 && var.backup_retention_count <= 365 && floor(var.backup_retention_count) == var.backup_retention_count
    error_message = "backup_retention_count must be a whole number from 1 to 365."
  }
}

variable "backup_start_time" {
  type        = string
  description = "UTC start of the daily backup window, in HH:MM"
  default     = "03:00"

  validation {
    condition     = can(regex("^([01][0-9]|2[0-3]):[0-5][0-9]$", var.backup_start_time))
    error_message = "backup_start_time must be HH:MM in 24-hour UTC, for example \"03:00\"."
  }
}

variable "maintenance_window" {
  type = object({
    day          = number
    hour         = number
    update_track = optional(string, "stable")
  })
  description = "Weekly maintenance window in UTC, with Monday as day 1. Null lets Google choose."
  default = {
    day  = 7
    hour = 4
  }

  validation {
    condition = var.maintenance_window == null || try(
      var.maintenance_window.day >= 1 && var.maintenance_window.day <= 7 &&
      var.maintenance_window.hour >= 0 && var.maintenance_window.hour <= 23 &&
      contains(["canary", "stable", "week5"], var.maintenance_window.update_track),
      false
    )
    error_message = "maintenance_window needs day 1-7, hour 0-23 and update_track canary, stable or week5."
  }
}

variable "deletion_protection" {
  type        = bool
  description = "Block deletion of the instance through Terraform and through the API, and refuse to drop the database. Set false and apply before a destroy."
  default     = true
}

variable "labels" {
  type        = map(string)
  description = "Labels to apply to the instance and its alerts"
  default     = {}

  validation {
    condition = alltrue([
      for k, v in var.labels : can(regex("^[a-z][a-z0-9_-]{0,62}$", k)) && can(regex("^[a-z0-9_-]{0,63}$", v))
    ])
    error_message = "labels keys must be 1-63 lowercase letters, digits, underscores or hyphens starting with a letter, and values up to 63 of the same characters."
  }
}

# --- Alerts ------------------------------------------------------------------
# Same shape as the AWS modules: the alerts always exist, and stay silent until
# a caller supplies somewhere to send them.

variable "enable_alerts" {
  type        = bool
  description = "Create the Cloud Monitoring alert policies"
  default     = true
}

variable "notification_channels" {
  type        = list(string)
  description = "Cloud Monitoring notification channel IDs to notify. Empty = alerts exist but notify nothing."
  default     = []
}

# Cloud SQL publishes CPU, memory and disk as fractions of 0-1. The thresholds
# are percentages, like the Azure module, and divided by 100 in main.tf.
variable "cpu_alarm_threshold" {
  type        = number
  description = "CPU utilisation percentage to alert above"
  default     = 80

  validation {
    condition     = var.cpu_alarm_threshold > 0 && var.cpu_alarm_threshold <= 100
    error_message = "cpu_alarm_threshold must be between 0 and 100 (percentage)."
  }
}

# The AWS module alarms on free bytes; Cloud SQL publishes the fraction used.
# The threshold is therefore inverted, not translated.
variable "memory_alarm_threshold" {
  type        = number
  description = "Memory utilisation percentage to alert above"
  default     = 85

  validation {
    condition     = var.memory_alarm_threshold > 0 && var.memory_alarm_threshold <= 100
    error_message = "memory_alarm_threshold must be between 0 and 100 (percentage)."
  }
}

variable "disk_alarm_threshold" {
  type        = number
  description = "Disk utilisation percentage to alert above. Matches the AWS module's floor of 15% free."
  default     = 85

  validation {
    condition     = var.disk_alarm_threshold > 0 && var.disk_alarm_threshold <= 100
    error_message = "disk_alarm_threshold must be between 0 and 100 (percentage)."
  }
}

variable "connections_alarm_threshold" {
  type        = number
  description = "Connection count to alert above. Null = 80% of max_connections."
  default     = null

  validation {
    condition     = var.connections_alarm_threshold == null || try(var.connections_alarm_threshold > 0, false)
    error_message = "connections_alarm_threshold must be null or greater than 0."
  }
}
