variable "name" {
  type        = string
  description = "Name of the flexible server and the resources named after it"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.name))
    error_message = "name must be 3-63 characters of lowercase letters, digits and hyphens, and must start and end with a letter or digit."
  }
}

variable "resource_group_name" {
  type        = string
  description = "Resource group that holds the server"
}

variable "location" {
  type        = string
  description = "Azure region, for example \"eastus\""
}

variable "db_name" {
  type        = string
  description = "Name of the database created on the server"
  default     = "postgres"
}

variable "engine_version" {
  type        = string
  description = "PostgreSQL major version"
  default     = "17"
}

# Azure sizes a flexible server by SKU name rather than by an instance class.
# The prefix picks the tier: B is burstable, GP is general purpose, MO is
# memory optimised.
variable "sku_name" {
  type        = string
  description = "Flexible server SKU, for example \"GP_Standard_D2ds_v5\". B-prefixed SKUs are burstable and cannot run zone-redundant high availability."
  default     = "GP_Standard_D2ds_v5"

  validation {
    condition     = can(regex("^(B|GP|MO)_", var.sku_name))
    error_message = "sku_name must start with B_, GP_ or MO_ (for example \"GP_Standard_D2ds_v5\")."
  }
}

# Azure allows only a fixed ladder of storage sizes, unlike the arbitrary GiB
# the AWS module accepts. Picking a value off the ladder fails at apply, so it
# is rejected here instead.
variable "storage_gb" {
  type        = number
  description = "Storage size in GiB. Azure allows only these steps, and storage can grow but never shrink."
  default     = 128

  validation {
    condition     = contains([32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384], var.storage_gb)
    error_message = "storage_gb must be one of: 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384 (the sizes Azure offers in whole GiB). Azure's largest size is not a whole number of GiB and is not reachable through this variable."
  }
}

variable "storage_tier" {
  type        = string
  description = "Performance tier for the storage. Null takes the default that Azure pairs with storage_gb. Raising it buys IOPS without buying capacity."
  default     = null

  validation {
    condition     = var.storage_tier == null || contains(["P4", "P6", "P10", "P15", "P20", "P30", "P40", "P50", "P60", "P70", "P80"], coalesce(var.storage_tier, "P4"))
    error_message = "storage_tier must be one of the tiers Azure offers: P4, P6, P10, P15, P20, P30, P40, P50, P60, P70, P80."
  }

  # Each storage size carries a default tier, and the documented feature is
  # raising it to buy IOPS without buying capacity. Going below the default is
  # what Azure refuses, so that is what is checked here. No ceiling is asserted:
  # which of the higher tiers a given size accepts is not something this module
  # can state confidently, and rejecting a valid configuration is worse than
  # letting Azure be the one to refuse an invalid one.
  validation {
    # try() keeps a tier that is not a tier at all from erroring here; the rule
    # above is the one that reports that.
    condition = var.storage_tier == null || try(index(
      ["P4", "P6", "P10", "P15", "P20", "P30", "P40", "P50", "P60", "P70", "P80"],
      coalesce(var.storage_tier, "P4"),
      ) >= index(
      ["P4", "P6", "P10", "P15", "P20", "P30", "P40", "P50", "P60", "P70", "P80"],
      lookup({
        "32"    = "P4"
        "64"    = "P6"
        "128"   = "P10"
        "256"   = "P15"
        "512"   = "P20"
        "1024"  = "P30"
        "2048"  = "P40"
        "4096"  = "P50"
        "8192"  = "P60"
        "16384" = "P70"
      }, tostring(var.storage_gb), "P4"),
    ), true)
    error_message = "storage_tier is below the tier this storage_gb starts at. A size can be raised to a higher tier to buy IOPS, but not lowered below its own default."
  }
}

# The AWS module takes a storage ceiling; Azure only offers a switch, and grows
# the volume in steps on its own.
variable "auto_grow_enabled" {
  type        = bool
  description = "Let Azure grow the storage volume as it fills. There is no ceiling to set, unlike the AWS module's max_storage_gb."
  default     = true
}

variable "delegated_subnet_id" {
  type        = string
  description = "Subnet delegated to Microsoft.DBforPostgreSQL/flexibleServers. The server joins the virtual network and gets no public endpoint."
}

variable "virtual_network_id" {
  type        = string
  description = "Virtual network linked to the private DNS zone, so clients in it resolve the server's private name"
}

variable "private_dns_zone_id" {
  type        = string
  description = "Existing private DNS zone to use. Null creates one named \"<name>.private.postgres.database.azure.com\"."
  default     = null
}

variable "username" {
  type        = string
  description = "Administrator login. Ignored when password authentication is disabled."
  default     = "psqladmin"
  sensitive   = true
}

variable "password" {
  type        = string
  description = "Administrator password. Ignored when password authentication is disabled."
  default     = null
  sensitive   = true

  validation {
    condition     = var.password == null || !var.entra_authentication_only
    error_message = "password cannot be set when entra_authentication_only is true: the server accepts no password logins and the value would be discarded."
  }

  # The mirror of the rule above. Password logins are on unless the caller turns
  # them off, and Azure rejects a server created with them on and no password.
  validation {
    condition     = var.password != null || var.entra_authentication_only
    error_message = "password must be set unless entra_authentication_only is true. Azure rejects a server that accepts password logins but has no administrator password."
  }
}

variable "enable_entra_authentication" {
  type        = bool
  description = "Accept Microsoft Entra ID logins. This is the analogue of the AWS module's IAM database authentication, and is what lets a workload identity reach the database without a password."
  default     = false
}

variable "entra_authentication_only" {
  type        = bool
  description = "Turn off password logins so Entra ID is the only way in. Requires enable_entra_authentication."
  default     = false

  validation {
    condition     = !var.entra_authentication_only || var.enable_entra_authentication
    error_message = "entra_authentication_only requires enable_entra_authentication to be true."
  }

  validation {
    condition     = !var.entra_authentication_only || var.entra_administrator_object_id != null
    error_message = "entra_authentication_only requires entra_administrator_object_id, otherwise the server accepts no password logins and has no Entra administrator either, leaving nobody able to connect."
  }
}

# Turning off password logins without naming an Entra administrator leaves a
# server nobody can connect to, so the module creates one.
variable "entra_administrator_object_id" {
  type        = string
  description = "Object ID of the Entra principal to make database administrator. Required when entra_authentication_only is true, so that somebody can still log in."
  default     = null
}

variable "entra_administrator_principal_name" {
  type        = string
  description = "Display name of the Entra administrator, for example a user principal name or a group name"
  default     = null

  validation {
    condition     = (var.entra_administrator_object_id == null) == (var.entra_administrator_principal_name == null)
    error_message = "entra_administrator_object_id and entra_administrator_principal_name must be set together."
  }
}

variable "entra_administrator_principal_type" {
  type        = string
  description = "What kind of Entra principal the administrator is"
  default     = "ServicePrincipal"

  validation {
    condition     = contains(["User", "Group", "ServicePrincipal"], var.entra_administrator_principal_type)
    error_message = "entra_administrator_principal_type must be one of: User, Group, ServicePrincipal."
  }
}

variable "tenant_id" {
  type        = string
  description = "Entra ID tenant that owns the administrator identities. Required when enable_entra_authentication is true."
  default     = null

  validation {
    condition     = !var.enable_entra_authentication || var.tenant_id != null
    error_message = "tenant_id must be set when enable_entra_authentication is true."
  }
}

variable "high_availability_enabled" {
  type        = bool
  description = "Run a standby in a second zone. Roughly doubles cost. Not available on burstable (B_) SKUs."
  default     = false

  validation {
    condition     = !var.high_availability_enabled || !startswith(var.sku_name, "B_")
    error_message = "Zone-redundant high availability is not offered on burstable SKUs. Move to a GP_ or MO_ SKU first."
  }
}

variable "high_availability_mode" {
  type        = string
  description = "ZoneRedundant puts the standby in another zone and survives a zone outage. SameZone only survives a node failure, and is the fallback in regions with no zones."
  default     = "ZoneRedundant"

  validation {
    condition     = contains(["ZoneRedundant", "SameZone"], var.high_availability_mode)
    error_message = "high_availability_mode must be ZoneRedundant or SameZone."
  }
}

variable "backup_retention_days" {
  type        = number
  description = "Days to retain automated backups"
  default     = 7

  validation {
    condition     = var.backup_retention_days >= 7 && var.backup_retention_days <= 35
    error_message = "backup_retention_days must be between 7 and 35. Flexible Server has no shorter retention, and unlike AWS backups cannot be turned off."
  }
}

variable "geo_redundant_backup_enabled" {
  type        = bool
  description = "Copy backups to the paired region. Can only be set when the server is created."
  default     = false
}

variable "maintenance_window" {
  type = object({
    day_of_week  = number
    start_hour   = number
    start_minute = number
  })
  description = "Weekly maintenance window in UTC, with Sunday as day 0. Null lets Azure choose."
  default     = null

  validation {
    condition = var.maintenance_window == null || (
      var.maintenance_window.day_of_week >= 0 && var.maintenance_window.day_of_week <= 6 &&
      var.maintenance_window.start_hour >= 0 && var.maintenance_window.start_hour <= 23 &&
      var.maintenance_window.start_minute >= 0 && var.maintenance_window.start_minute <= 59
    )
    error_message = "maintenance_window needs day_of_week 0-6, start_hour 0-23 and start_minute 0-59."
  }
}

variable "zone" {
  type        = string
  description = "Availability zone for the primary. Null lets Azure choose. Changing it after creation moves the server."
  default     = null
}

# RDS lets a user CREATE EXTENSION for most extensions without preparation.
# Azure refuses unless the extension is allow-listed on the server first, and
# the list starts empty -- so Onyx's own migrations fail on a fresh server with
# "extension pgcrypto is not allow-listed for users in Azure Database for
# PostgreSQL". These two are what those migrations create.
variable "allowed_extensions" {
  type        = list(string)
  description = "Extensions users may CREATE on this server, written to the azure.extensions server parameter. Empty leaves the parameter alone, which means no extension can be created at all."
  default     = ["pgcrypto", "pg_trgm"]
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to the server and its alerts"
  default     = {}
}

# --- Alerts ------------------------------------------------------------------
# Same shape as the AWS modules: the alerts always exist, and stay silent until
# a caller supplies somewhere to send them.

variable "action_group_ids" {
  type        = list(string)
  description = "Monitor action groups to notify. Empty = alerts exist but notify nothing."
  default     = []
}

variable "cpu_alarm_threshold" {
  type        = number
  description = "cpu_percent threshold"
  default     = 80

  validation {
    condition     = var.cpu_alarm_threshold > 0 && var.cpu_alarm_threshold <= 100
    error_message = "cpu_alarm_threshold must be between 0 and 100 (percentage)."
  }
}

# Azure reports memory and storage as percentages used, where the AWS module
# alarms on bytes free. The thresholds are therefore inverted, not translated.
variable "memory_alarm_threshold" {
  type        = number
  description = "memory_percent threshold. The AWS module alarms on free bytes; Azure publishes percent used."
  default     = 85

  validation {
    condition     = var.memory_alarm_threshold > 0 && var.memory_alarm_threshold <= 100
    error_message = "memory_alarm_threshold must be between 0 and 100 (percentage)."
  }
}

variable "storage_alarm_threshold" {
  type        = number
  description = "storage_percent threshold. Matches the AWS module's floor of 15% free."
  default     = 85

  validation {
    condition     = var.storage_alarm_threshold > 0 && var.storage_alarm_threshold <= 100
    error_message = "storage_alarm_threshold must be between 0 and 100 (percentage)."
  }
}

variable "connections_alarm_threshold" {
  type        = number
  description = "active_connections threshold. Size it against the server's real max_connections, which scales with the SKU."
  default     = 500

  validation {
    condition     = var.connections_alarm_threshold > 0
    error_message = "connections_alarm_threshold must be greater than 0."
  }
}

variable "iops_alarm_threshold" {
  type        = number
  description = "disk_iops_consumed_percentage threshold. Azure publishes IOPS against the provisioned limit, which is more useful than the AWS module's absolute ReadIOPS count."
  default     = 90

  validation {
    condition     = var.iops_alarm_threshold > 0 && var.iops_alarm_threshold <= 100
    error_message = "iops_alarm_threshold must be between 0 and 100 (percentage)."
  }
}
